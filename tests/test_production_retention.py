"""Destructive operations use tiny newly-created fixtures, never satellite archives."""
import json
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch
import numpy as np
from ges_next.production.assets import write_json, digest
from ges_next.production.jpeg_layers import encode_jpeg, encode_mask
from ges_next.production.journal import Journal
from ges_next.production.retention import Retention

UTC='2026-10-20T13:00:00Z'


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.root=Path('reports/production_retention_fixtures')/uuid.uuid4().hex
        self.root=self.root.resolve()
        self.j=Journal(self.root/'journal.sqlite')
        self.job=self.j.create_job(self.root/'job',{'required_capabilities':['groundEnabled']})
        self.package=self.root/'job'
        self.raw=self.package/'raw/scan.dat';self.raw.parent.mkdir()
        self.raw.write_bytes(b'new test input only')
        self.source=self.j.register_input(self.job,UTC,self.raw,'l1')
        rgb=np.zeros((8,8,3),np.uint8)
        assets=[encode_jpeg(self.package,'assets/base.jpg',rgb,95,'stock-clouds-day-without-ground-background'),
                encode_jpeg(self.package,'assets/night.jpg',rgb,95,'shared-static-night-background'),
                encode_mask(self.package,'assets/transmission.png',np.zeros((8,8),np.uint16),'stock-ground-transmission'),
                encode_mask(self.package,'assets/support.png',np.full((8,8),255,np.uint8),'actual-observation-support')]
        self.manifest=self.package/'commit.json'
        write_json(self.manifest,dict(schema='earthstudio.layered_jpeg.v1',utc=UTC,assets=assets))
        self.j.submit(self.job,UTC,self.manifest)
        self.proof=self.package/'fixture_proof.json'
        blend=self.package/'fixture.blend';blend.write_bytes(b'fixture only; not an actual Blender file')
        write_json(self.proof,dict(schema='earthstudio.blender.production_reopen.v1',
                   manifest_sha256=digest(self.manifest),independent_of_l1=True,
                   verified_capabilities=['groundEnabled'],test_fixture_only=True,
                   blend=dict(path=blend.name,bytes=blend.stat().st_size,sha256=digest(blend))))
        self.r=Retention(self.j)

    def tearDown(self): self.j.close()  # Keep evidence; no recursive teardown.

    def accepted(self):
        self.j.verify(self.job,UTC,self.proof)
        self.j.approve_profile(self.job,user_quality_accepted=True)

    def test_unverified_retained(self):
        with self.assertRaises(ValueError): self.r.plan(self.job,UTC)
        self.assertTrue(self.raw.exists())

    def test_verified_not_accepted_retained(self):
        self.j.verify(self.job,UTC,self.proof)
        with self.assertRaises(ValueError): self.r.plan(self.job,UTC)

    def test_owned_exact_delete(self):
        self.accepted()
        result=self.r.execute(self.r.plan(self.job,UTC))
        self.assertEqual(result['deleted_files'],1)
        self.assertFalse(self.raw.exists())
        self.assertTrue(self.manifest.exists())

    def test_changed_input_retained(self):
        self.accepted();self.raw.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.r.plan(self.job,UTC)
        self.assertTrue(self.raw.exists())

    def test_corrupt_output_retained(self):
        self.accepted();(self.package/'assets/base.jpg').write_bytes(b'bad')
        with self.assertRaises(ValueError): self.r.plan(self.job,UTC)
        self.assertTrue(self.raw.exists())

    def test_verified_gate_rehashes_without_redecoding_identical_bytes(self):
        self.accepted()
        with patch('PIL.Image.Image.load',side_effect=AssertionError('redundant decode')):
            self.j.gate(self.job,UTC)
        (self.package/'assets/base.jpg').write_bytes(b'changed exact bytes')
        with self.assertRaises(ValueError):self.j.gate(self.job,UTC)

    def test_changed_proof_retained(self):
        self.accepted();self.proof.write_text('{}')
        with self.assertRaises(ValueError): self.r.plan(self.job,UTC)

    def test_missing_editable_scene_retained(self):
        self.accepted();(self.package/'fixture.blend').unlink()
        with self.assertRaises(ValueError): self.r.plan(self.job,UTC)

    def test_new_profile_without_rebuild_recipe_retains_inputs(self):
        profile={'required_capabilities':['groundEnabled'],'require_rebuild_recipe':True}
        self.j.db.execute('UPDATE jobs SET profile=? WHERE id=?',(json.dumps(profile),self.job))
        with self.assertRaises(ValueError): self.j.verify(self.job,UTC,self.proof)
        self.assertTrue(self.raw.exists())

    def test_keep_intermediates(self):
        temp=self.package/'scratch/a.tif';temp.parent.mkdir();temp.write_bytes(b'fixture intermediate')
        self.j.register_input(self.job,UTC,temp,'temporary');self.accepted()
        self.j.db.execute('UPDATE jobs SET keep_temp=1 WHERE id=?',(self.job,))
        result=self.r.execute(self.r.plan(self.job,UTC))
        self.assertTrue(temp.exists());self.assertEqual(result['deleted_files'],1)

    def test_hardlink_retained(self):
        target=self.package/'raw/linked.dat';os.link(self.raw,target)
        self.j.db.execute('DELETE FROM claims WHERE source=?',(self.source,))
        self.j.db.execute('DELETE FROM sources WHERE id=?',(self.source,))
        self.source=self.j.register_input(self.job,UTC,self.raw,'l1');self.accepted()
        self.assertEqual(self.r.plan(self.job,UTC)['candidates'],[])

    def test_other_step_claim_retained(self):
        self.accepted();self.j.claim(self.job,'2026-10-20T13:10:00Z',self.source)
        self.assertEqual(self.r.plan(self.job,UTC)['candidates'],[])

    def test_keep_l1(self):
        self.accepted();self.j.db.execute('UPDATE jobs SET keep_l1=1 WHERE id=?',(self.job,))
        self.assertEqual(self.r.plan(self.job,UTC)['candidates'],[])

    def test_stale_plan_retained(self):
        self.accepted();plan=self.r.plan(self.job,UTC)
        self.j.claim(self.job,'2026-10-20T13:10:00Z',self.source)
        with self.assertRaises(ValueError): self.r.execute(plan)
        self.assertTrue(self.raw.exists())

    def test_reused_input_preserved(self):
        reused=self.root/'historical.dat';reused.write_bytes(b'read only')
        self.j.register_input(self.job,UTC,reused,'reused');self.accepted()
        result=self.r.execute(self.r.plan(self.job,UTC))
        self.assertTrue(reused.exists());self.assertEqual(len(result['retained']),1)

    def test_escape_rejected(self):
        with self.assertRaises(ValueError): self.j.register_input(self.job,UTC,self.root/'outside.dat','l1')

    def test_crash_after_deletion_recovered(self):
        self.accepted();plan=self.r.plan(self.job,UTC)
        from ges_next.production.owned_files import delete_verified
        def crash(path,stamp):
            delete_verified(path,stamp)
            raise RuntimeError('simulated process interruption after physical deletion')
        with patch('ges_next.production.retention.delete_verified',crash):
            with self.assertRaises(RuntimeError): self.r.execute(plan)
        recovered=self.r.plan(self.job,UTC)
        self.assertEqual(recovered['candidates'],[])
        self.assertEqual(self.j.db.execute('SELECT deleted FROM sources WHERE id=?',(self.source,)).fetchone()[0],1)


if __name__=='__main__': unittest.main()
