"""Tiny fixture-only queue tests; no scientific/payload network claims."""
import hashlib
import io
import json
from pathlib import Path
import types
import unittest
import uuid
from unittest.mock import patch
import numpy as np
from ges_next.pipeline import runner
from ges_next.pipeline.locking import exclusive
from ges_next.pipeline.plan import create
from ges_next.production.assets import digest,record,write_json
from ges_next.production.jpeg_layers import encode_jpeg,encode_mask
from ges_next.production.profile import h9_profile
from ges_next.production.rebuild_recipe import BANDS


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.root=(Path('reports/pipeline_fixtures')/uuid.uuid4().hex).resolve();self.root.mkdir(parents=True)
        self.queue=self.root/'queue';self.calls=[];self.payloads={};self.produced=[]
        self.project=dict(Id='fixture',StartUtc='2026-10-20T13:00:00Z',EndUtc='2026-10-20T13:10:00Z',IntervalMinutes=10,
            SatelliteSelection=dict(Mode='manual',Preset='h9',Satellites=['himawari9']),
            Production=dict(Format='jpeg',HimawariDiskSize=11000,NightLightMetres=1000,JpegQuality=95,KeepL1=False,KeepIntermediates=False))
        self.records=[]
        for minute in ('00','10'):
            keys=[];sizes=[]
            for band in BANDS:
                for segment in range(1,11):
                    key=f'AHI-L1b-FLDK/2026/10/20/13{minute}/HS_H09_20261020_13{minute}_{band}_FLDK_R10_S{segment:02}10.DAT.bz2'
                    self.payloads[key]=key.encode();keys.append(key);sizes.append(len(key.encode()))
            utc=f'2026-10-20T13:{minute}:00Z'
            self.records.append(dict(requested_utc=utc,source='himawari9',state='available',native=dict(satellite='himawari9',
                observed_utc=utc,bucket='noaa-himawari9',keys=keys,sizes=sizes,etags=['"fixture"']*60)))
        self.inventory=self.root/'inventory.json'
        def get_object(**kwargs):
            self.calls.append(kwargs);self.assertEqual(kwargs['IfMatch'],'"fixture"')
            return dict(Body=io.BytesIO(self.payloads[kwargs['Key']]))
        self.client=types.SimpleNamespace(get_object=get_object)
        self.workers=types.SimpleNamespace(produce=self.produce,verify=lambda package:None)
        self.space=patch('shutil.disk_usage',return_value=types.SimpleNamespace(free=100*1024**3));self.space.start();self.addCleanup(self.space.stop)
        def tiny_profile(q,n):
            value=h9_profile(q,n);value['grid_shape']=[8,8];return value
        self.profile_patch=patch('ges_next.pipeline.runner.h9_profile',tiny_profile);self.profile_patch.start();self.addCleanup(self.profile_patch.stop)
        self.make_plan()

    def make_plan(self):
        write_json(self.inventory,dict(project_id='fixture',finished=True,project_spec=self.project,records=self.records))
        return create(self.project,self.inventory,self.queue)

    def produce(self,step,package,profile):
        self.produced.append(step['utc']);j=runner.journal_for(package)
        try:
            job=j.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()['id']
            paths=json.loads((package/'input_selection.json').read_text());rows=[]
            for source in paths:
                source=Path(source);owned=source.is_relative_to(package)
                j.register_input(job,step['utc'],source,'l1' if owned else 'reused')
                if owned:j.register_input(job,step['utc'],Path(str(source)+'.json'),'l1')
                receipt=json.loads(Path(str(source)+'.json').read_text())
                rows.append(dict(bucket='noaa-himawari9',**{k:receipt[k] for k in ('key','bytes','etag','sha256')}))
            temp=package/'scratch/fixture.bin';temp.parent.mkdir(exist_ok=True);temp.write_bytes(b'tiny owned scratch')
            j.register_input(job,step['utc'],temp,'temporary')
            rgb=np.zeros((8,8,3),np.uint8)
            assets=[encode_jpeg(package,'assets/base.jpg',rgb,95,'stock-clouds-day-without-ground-background'),
                encode_jpeg(package,'assets/night.jpg',rgb,95,'shared-static-night-background'),
                encode_mask(package,'assets/transmission.png',np.zeros((8,8),np.uint16),'stock-ground-transmission'),
                encode_mask(package,'assets/support.png',np.full((8,8),255,np.uint8),'actual-observation-support')]
            recipe=package/'rebuild_recipe.json';write_json(recipe,dict(schema='earthstudio.h9.rebuild.v1',utc=step['utc'],inputs=rows))
            write_json(package/'commit.json',dict(schema='earthstudio.layered_jpeg.v1',utc=step['utc'],assets=assets,grid=dict(shape=[8,8],extent=[-180,-90,180,90],crs='EPSG:4326'),quality=dict(psnr_db=40),
                rebuild_recipe=record(package,recipe,'single-scan-rebuild-recipe')))
            j.submit(job,step['utc'],package/'commit.json')
            blend=package/'fixture.blend';blend.write_bytes(b'fixture only, not Blender data')
            write_json(package/'blender_reopen.json',dict(schema='earthstudio.blender.production_reopen.v1',
                manifest_sha256=digest(package/'commit.json'),independent_of_l1=True,test_fixture_only=True,
                verified_capabilities=h9_profile(95,1000)['required_capabilities'],blend=record(package,blend,'fixture')))
        finally:j.close()

    def run_queue(self,**kwargs):return runner.run(self.queue,self.client,self.workers,**kwargs)

    def test_cross_project_arbitrary_overlap_only_produces_new_scans(self):
        import copy
        self.run_queue();runner.accept_quality(self.queue);self.run_queue()
        source=self.queue
        before={str(p):digest(p) for p in source.rglob('*') if p.is_file() and p.name!='queue.lock'}
        self.project.update(Id='second',StartUtc='2026-10-20T13:10:00Z',EndUtc='2026-10-20T13:20:00Z')
        extra=json.loads(json.dumps(self.records[1]).replace('13:10:00','13:20:00').replace('1310','1320'))
        self.records=[self.records[1],extra]
        for key in extra['native']['keys']:self.payloads[key]=key.encode()
        self.queue=self.root/'second'
        write_json(self.inventory,dict(project_id='second',finished=True,project_spec=self.project,records=self.records))
        plan=create(self.project,self.inventory,self.queue,reuse_source=source)
        self.assertEqual(plan['reused_scans'],1);self.assertEqual(plan['new_scans'],1)
        self.assertEqual(runner.package_for(self.queue,self.records[0]['requested_utc']),runner.package_for(source,self.records[0]['requested_utc']))
        calls=len(self.calls);produced=len(self.produced)
        self.assertEqual(self.run_queue()['phase'],'awaiting-quality')
        runner.accept_quality(self.queue);self.assertEqual(self.run_queue()['phase'],'complete')
        self.assertEqual(len(self.calls)-calls,60);self.assertEqual(len(self.produced)-produced,1)
        from ges_next.layered_sequence.collection import from_queue
        from ges_next.layered_sequence.package import build
        paths,interval=from_queue(self.queue)
        delivery=self.root/'delivery'
        manifest=build(paths,delivery,interval)
        self.assertEqual([n['utc'] for n in manifest['nodes']],[r['requested_utc'] for r in self.records])
        self.assertFalse(any(n['missing'] for n in manifest['nodes']))
        from ges_next.production.assets import verify_assets
        verify_assets(delivery,manifest['files'])
        self.assertEqual(before,{str(p):digest(p) for p in source.rglob('*') if p.is_file() and p.name!='queue.lock'})

    def test_cross_project_all_reused_and_chained_without_payload(self):
        self.run_queue();runner.accept_quality(self.queue);self.run_queue()
        source=self.queue
        self.project['Id']='second'
        write_json(self.inventory,dict(project_id='second',finished=True,project_spec=self.project,records=self.records))
        self.queue=self.root/'all_reused'
        plan=create(self.project,self.inventory,self.queue,reuse_source=source)
        calls=len(self.calls);produced=len(self.produced)
        self.assertEqual(plan['new_scans'],0)
        self.assertEqual(self.run_queue()['phase'],'complete')
        chained=self.root/'chained'
        plan=create(self.project,self.inventory,chained,reuse_source=self.queue)
        self.assertEqual(plan['reused_scans'],2)
        self.queue=chained
        self.assertEqual(self.run_queue()['phase'],'complete')
        self.assertEqual(len(self.calls),calls);self.assertEqual(len(self.produced),produced)
        package=runner.package_for(source,self.records[0]['requested_utc'])
        (package/'assets/base.jpg').write_bytes(b'broken')
        with self.assertRaises(Exception):create(self.project,self.inventory,self.root/'broken',reuse_source=source)

    def test_cross_project_rejects_unfinished_incompatible_and_no_overlap(self):
        from ges_next.pipeline.extension import reuse_completed
        steps=json.loads((self.queue/'plan.json').read_text(encoding='utf-8'))['steps']
        with self.assertRaisesRegex(ValueError,'已完成'):reuse_completed(self.queue,self.project,steps)
        self.run_queue();runner.accept_quality(self.queue);self.run_queue()
        with self.assertRaisesRegex(ValueError,'没有可复用'):reuse_completed(self.queue,self.project,[])
        changed=dict(self.project,IntervalMinutes=30)
        with self.assertRaisesRegex(ValueError,'IntervalMinutes'):reuse_completed(self.queue,changed,steps)
        import copy
        changed=copy.deepcopy(steps);changed[0]['objects'][0]['etag']='changed'
        with self.assertRaisesRegex(ValueError,'目录身份'):reuse_completed(self.queue,self.project,changed)

    def test_single_frame_normal_plan_download_verify_accept_and_finish(self):
        self.project.update(CaptureMode='single',EndUtc=self.project['StartUtc'])
        self.records=self.records[:1]
        self.queue=self.root/'single_queue';plan=self.make_plan()
        self.assertEqual(plan['requested_nodes'],1)
        self.assertEqual(plan['project']['CaptureMode'],'single')
        state=self.run_queue();self.assertEqual(state['phase'],'awaiting-quality')
        self.assertEqual(len(self.calls),60)
        runner.accept_quality(self.queue);state=self.run_queue()
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(self.calls),60)
        self.assertEqual(len(state['completed']),1)

    def test_first_sample_then_accept_and_resume(self):
        state=self.run_queue();self.assertEqual(state['phase'],'awaiting-quality');self.assertEqual(len(self.calls),60)
        first=runner.package_for(self.queue,self.records[0]['requested_utc'])
        self.assertEqual(len(list(first.rglob('*.bz2'))),60);self.assertEqual(len(self.produced),1)
        runner.accept_quality(self.queue);state=self.run_queue()
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(self.calls),120)
        self.assertEqual(list(self.queue.rglob('*.bz2')),[]);self.assertEqual(list(self.queue.rglob('fixture.bin')),[])
        self.assertEqual(len(list(self.queue.rglob('rebuild_recipe.json'))),2)
        self.assertTrue((self.queue/'sequence_index.json').exists())
        self.run_queue();self.assertEqual(len(self.calls),120);self.assertEqual(len(self.produced),2)

    def test_append_reuses_accepted_scans_after_l1_cleanup(self):
        import copy
        self.run_queue();runner.accept_quality(self.queue);self.run_queue()
        previous=self.queue;original=digest(previous/'plan.json')
        row=copy.deepcopy(self.records[-1]);row['requested_utc']='2026-10-20T13:20:00Z';row['native']['observed_utc']=row['requested_utc']
        keys=[key.replace('1310','1320') for key in row['native']['keys']]
        for key in keys:self.payloads[key]=key.encode()
        row['native'].update(keys=keys,sizes=[len(k.encode()) for k in keys]);self.records.append(row)
        self.project['EndUtc']=row['requested_utc'];self.queue=self.root/'appended'
        write_json(self.inventory,dict(project_id='fixture',finished=True,project_spec=self.project,records=self.records))
        plan=create(self.project,self.inventory,self.queue,previous=previous)
        self.assertEqual(plan['reused_scans'],2);self.assertEqual(plan['new_scans'],1)
        self.assertEqual(plan['download_bytes'],sum(row['native']['sizes']))
        self.assertEqual(self.run_queue()['phase'],'awaiting-quality')
        runner.accept_quality(self.queue);self.assertEqual(self.run_queue()['phase'],'complete')
        self.assertEqual(len(self.calls),180);self.assertEqual(len(self.produced),3)
        self.assertEqual(digest(previous/'plan.json'),original)
        self.assertEqual(list(previous.rglob('*.bz2')),[])
        self.assertEqual(runner.package_for(self.queue,self.records[0]['requested_utc']),runner.package_for(previous,self.records[0]['requested_utc']))

    def test_append_rejects_unfinished_or_changed_profile(self):
        self.project['EndUtc']='2026-10-20T13:20:00Z'
        from ges_next.pipeline.extension import inherit
        with self.assertRaises(ValueError):inherit(self.queue,self.project,[])

    def test_unaccepted_cannot_delete_or_advance(self):
        self.run_queue();self.run_queue();self.assertEqual(len(self.calls),60);self.assertEqual(len(self.produced),1)
        self.assertEqual(len(list(self.queue.rglob('*.bz2'))),60)

    def test_accept_before_sample_rejected(self):
        with self.assertRaises(ValueError):runner.accept_quality(self.queue)
        self.assertEqual(self.calls,[])

    def test_low_space_waits_and_user_can_pause_before_download(self):
        with patch('shutil.disk_usage',return_value=types.SimpleNamespace(free=0)):
            def report(value):
                if value['phase']=='waiting-resources':write_json(self.queue/'pause_requested.json',dict(requested=True))
            self.assertEqual(self.run_queue(report=report)['phase'],'paused-user')
        self.assertEqual(self.calls,[])

    def test_missing_requires_explicit_choice(self):
        self.queue=self.root/'missing';self.records[1]['state']='missing';self.make_plan()
        self.assertEqual(self.run_queue()['phase'],'awaiting-missing-decision');self.assertEqual(self.calls,[])
        self.assertEqual(self.run_queue(allow_missing=True)['phase'],'awaiting-quality')

    def test_corrupt_formal_preserves_raw_and_stops_next(self):
        self.run_queue();first=runner.package_for(self.queue,self.records[0]['requested_utc'])
        runner.accept_quality(self.queue);(first/'assets/base.jpg').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.run_queue()
        self.assertEqual(len(self.calls),60);self.assertEqual(len(list(first.rglob('*.bz2'))),60)

    def test_keep_options(self):
        self.queue=self.root/'retained';self.project['Production'].update(KeepL1=True,KeepIntermediates=True);self.make_plan()
        self.run_queue();runner.accept_quality(self.queue);self.run_queue()
        self.assertEqual(len(list(self.queue.rglob('*.bz2'))),120);self.assertEqual(len(list(self.queue.rglob('fixture.bin'))),2)

    def test_verified_historical_cache_read_in_place(self):
        first_step=json.loads((self.queue/'plan.json').read_text(encoding='utf-8'))['steps'][0]
        from ges_next.pipeline.transfer import acquire
        cached=self.root/'historical';acquire(first_step,cached,None,self.client,lambda value:None)
        old={p:digest(p) for p in cached.rglob('*') if p.is_file()};self.calls.clear()
        self.run_queue(cache_root=cached);self.assertEqual(self.calls,[])
        runner.accept_quality(self.queue);self.run_queue(cache_root=cached)
        self.assertEqual(len(self.calls),60)
        self.assertTrue(all(p.exists() and digest(p)==value for p,value in old.items()))

    def test_queue_lock(self):
        with exclusive(self.queue/'queue.lock'):
            with self.assertRaises((OSError,ValueError)):self.run_queue()
        self.assertEqual(self.calls,[])

    def test_global_not_silently_replaced(self):
        self.project['SatelliteSelection']=dict(Mode='auto',Preset='global',Satellites=[])
        with self.assertRaises(ValueError):create(self.project,self.inventory,self.root/'global')

    def test_plan_tampering_rejected(self):
        (self.queue/'plan.json').write_text('{}')
        with self.assertRaises(ValueError):self.run_queue()

    def test_regional_scope_not_ignored(self):
        self.project['Scope']='region'
        with self.assertRaises(ValueError):create(self.project,self.inventory,self.root/'region')

    def test_storage_change_requires_new_inventory(self):
        self.project['DataDirectory']=str(self.root/'other-drive')
        with self.assertRaises(ValueError):create(self.project,self.inventory,self.root/'changed-storage')

    def test_truncated_download_retry(self):
        calls=0;original=self.client.get_object
        def short(**kwargs):
            nonlocal calls
            calls+=1
            return dict(Body=io.BytesIO(b'truncated')) if calls==1 else original(**kwargs)
        self.client.get_object=short
        with self.assertRaises(ValueError):self.run_queue()
        # Parallel sibling transfers may finish. Every installed input must have
        # a matching receipt; the truncated object itself must never be installed.
        from ges_next.pipeline.transfer import cached
        objects={Path(i['key']).name:i for i in json.loads((self.queue/'plan.json').read_text(encoding='utf-8'))['steps'][0]['objects']}
        verified=set()
        for path in self.queue.rglob('*.bz2'):
            self.assertTrue(cached(path,objects[path.name]));verified.add(objects[path.name]['key'])
        before=len(self.calls)
        self.client.get_object=original
        self.assertEqual(self.run_queue()['phase'],'awaiting-quality')
        self.assertFalse(verified.intersection(call['Key'] for call in self.calls[before:]))
        self.assertEqual(len({call['Key'] for call in self.calls}),60)

    def test_serial_resume_uses_returned_verification_evidence(self):
        self.assertEqual(self.run_queue()['phase'],'awaiting-quality')
        runner.accept_quality(self.queue)
        paths=[]
        def verify(package):
            path=package/'alternate_verification.json'
            (package/'blender_reopen.json').replace(path)
            paths.append(path)
            return path
        self.workers.verify=verify
        state=self.run_queue()
        self.assertEqual(state['phase'],'complete')
        self.assertEqual(len(state['completed']),2)
        self.assertTrue(paths)
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertTrue(all(not (path.parent/'blender_reopen.json').exists() for path in paths))

    def test_blender_failure_retains_inputs(self):
        self.workers.verify=lambda package: (_ for _ in ()).throw(RuntimeError('fixture Blender failure'))
        with self.assertRaises(RuntimeError):self.run_queue()
        self.assertEqual(len(self.calls),60);self.assertEqual(len(list(self.queue.rglob('*.bz2'))),60)

    def test_failure_has_stage_and_recovery_clears_stale_error(self):
        verify=self.workers.verify
        self.workers.verify=lambda package: (_ for _ in ()).throw(RuntimeError('fixture verification error'))
        with self.assertRaises(RuntimeError):self.run_queue()
        failed=json.loads((self.queue/'state.json').read_text())
        self.assertEqual(failed['error_stage'],'verifying');self.assertIn('updated_utc',failed)
        reason=json.loads((self.queue/'last_failure.json').read_text())
        self.assertEqual(reason['stage'],'verifying');self.assertEqual(reason['error_type'],'RuntimeError')
        self.workers.verify=verify
        state=self.run_queue()
        self.assertEqual(state['phase'],'awaiting-quality');self.assertNotIn('error',state)
        self.assertEqual(state['last_error']['message'],'fixture verification error')
        self.assertEqual(len(self.calls),60,'verified downloads must be reused after recovery')
        events=[json.loads(line) for line in (self.queue/'events.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['phase']=='failed-inputs-preserved' for e in events))
        self.assertEqual(events[-1]['phase'],'awaiting-quality')

    def test_encoding_retry_only_identical(self):
        pixels=np.zeros((8,8,3),np.uint8)
        encode_jpeg(self.root,'retry.jpg',pixels)
        encode_jpeg(self.root,'retry.jpg',pixels,resume=True)
        saved=digest(self.root/'retry.jpg')
        with self.assertRaises(FileExistsError):encode_jpeg(self.root,'retry.jpg',pixels+255,resume=True)
        self.assertEqual(digest(self.root/'retry.jpg'),saved)


if __name__=='__main__':unittest.main()

