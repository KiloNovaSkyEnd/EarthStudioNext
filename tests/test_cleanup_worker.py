"""Full child-process cleanup on tiny owned queue fixtures only."""
import json,os,unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_pipeline as fixtures
from ges_next.pipeline import runner,workers
from ges_next.production.assets import digest


class CleanupWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PipelineTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.worker=workers.Workers('unused','unused','unused','unused',lambda value:None)
        self.worker.engine=Path.cwd()
        original=workers.module
        def staged(name,args,root,log,report,environment=None,watchdog=None):
            self.assertEqual(name,'ges_next.production.cleanup')
            return original('tests.cleanup_child_fixture',args,root,log,report,environment,watchdog)
        self.patch=patch.object(workers,'module',staged);self.patch.start();self.addCleanup(self.patch.stop)

    def prepare(self,accept=True,keep=False):
        if keep:
            self.f.project['Production']['KeepL1']=True;self.f.queue=self.f.root/'keep';self.f.make_plan()
        self.assertEqual(self.f.run_queue()['phase'],'awaiting-quality')
        if accept:runner.accept_quality(self.f.queue)
        package=runner.package_for(self.f.queue,'2026-10-20T13:00:00Z')
        self.raw=[p for p in (package/'raw').rglob('*') if p.is_file()]
        return package

    def test_approved_child_reclaims_only_owned_inputs_and_preserves_assets(self):
        p=self.prepare();before={str(f):digest(f) for f in (p/'assets').iterdir()}
        result=self.worker.cleanup(p)
        self.assertEqual(result['deleted_files'],121);self.assertFalse(any(f.exists() for f in self.raw))
        self.assertEqual(before,{str(f):digest(f) for f in (p/'assets').iterdir()})
        checks=json.loads((p/'cleanup_validation.json').read_text());self.assertTrue(checks['isolated_process'])
        self.assertNotEqual(checks['pid'],os.getpid());self.assertEqual(checks['protected_deletions'],121)

    def test_parallel_queue_counts_completed_only_after_real_cleanup_child_success(self):
        from ges_next.pipeline import parallel
        self.prepare();self.f.workers.cleanup=self.worker.cleanup
        with patch.object(parallel,'capacity',return_value=2),patch('ges_next.pipeline.concurrency.Concurrency.admit',return_value=True):
            state=parallel.run(self.f.queue,self.f.client,self.f.workers,max_compute=2,prefetch=2)
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),2)
        self.assertEqual(len(self.f.produced),2,'Already committed first frame must not be produced again')
        for utc in state['completed']:
            p=runner.package_for(self.f.queue,utc)
            self.assertTrue(json.loads((p/'cleanup_validation.json').read_text())['isolated_process'])
            self.assertFalse(any(f.is_file() for f in (p/'raw').rglob('*')))

    def test_unaccepted_job_cannot_reclaim_inputs(self):
        p=self.prepare(accept=False)
        with self.assertRaises(RuntimeError):self.worker.cleanup(p)
        self.assertTrue(all(f.exists() for f in self.raw));self.assertFalse((p/'cleanup_result.json').exists())

    def test_corrupt_output_cannot_reclaim_inputs(self):
        p=self.prepare();(p/'assets/base.jpg').write_bytes(b'tampered')
        with self.assertRaises(RuntimeError):self.worker.cleanup(p)
        self.assertTrue(all(f.exists() for f in self.raw))

    def test_changed_input_rejected_before_any_deletion(self):
        p=self.prepare();self.raw[0].write_bytes(b'tampered')
        with self.assertRaises(RuntimeError):self.worker.cleanup(p)
        self.assertTrue(all(f.exists() for f in self.raw))

    def test_keep_l1_remains_effective_in_child(self):
        p=self.prepare(keep=True);result=self.worker.cleanup(p)
        self.assertEqual(result['deleted_files'],1);self.assertTrue(all(f.exists() for f in self.raw))

    def test_interrupted_child_recovers_durable_intents_without_reproduction(self):
        p=self.prepare();before=len(self.f.produced);self.worker.environment['CLEANUP_FIXTURE_CRASH_AFTER']='3'
        with self.assertRaises(RuntimeError):self.worker.cleanup(p)
        self.assertGreater(len((p/'cleanup_intents.jsonl').read_text().splitlines()),0)
        self.worker.environment.clear();result=self.worker.cleanup(p)
        self.assertEqual(result['deleted_files'],118);self.assertFalse(any(f.exists() for f in self.raw))
        self.assertEqual(len(self.f.produced),before);self.assertTrue((p/'commit.json').exists())
