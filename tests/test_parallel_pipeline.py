import copy,json,time,threading
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_pipeline import PipelineTests
from ges_next.pipeline import runner,parallel
from ges_next.production.assets import write_json


class ParallelPipelineTests(unittest.TestCase):
    def setUp(self):
        self.f=PipelineTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        for minute in ('20','30'):
            row=copy.deepcopy(f.records[0]);row['requested_utc']=f'2026-10-20T13:{minute}:00Z'
            row['native']['observed_utc']=row['requested_utc'];keys=[]
            for key in row['native']['keys']:
                new=key.replace('1300','13'+minute);keys.append(new);f.payloads[new]=new.encode()
            row['native']['keys']=keys;row['native']['sizes']=[len(k.encode()) for k in keys];f.records.append(row)
        f.project['EndUtc']='2026-10-20T13:30:00Z';f.queue=f.root/'parallel';f.make_plan()

    def run_parallel(self):
        f=self.f
        with patch('ges_next.pipeline.parallel.capacity',return_value=2),patch('ges_next.pipeline.concurrency.Concurrency.admit',return_value=True):
            return parallel.run(f.queue,f.client,f.workers,max_compute=2,prefetch=2)

    def accept_first(self):
        self.assertEqual(self.f.run_queue()['phase'],'awaiting-quality');runner.accept_quality(self.f.queue)

    def test_loaded_plan_resolves_packages_without_disk_reads(self):
        root,plan,_=runner.load(self.f.queue)
        with patch('pathlib.Path.read_text',side_effect=AssertionError('plan reread')):
            for step in plan['steps']:
                self.assertEqual(runner.package_for(root,step['utc'],plan),
                    root/'steps'/step['utc'].replace('-','').replace(':',''))

    def test_committed_recovery_does_not_wait_for_fresh_science_to_finish(self):
        self.accept_first();f=self.f
        _,plan,_=runner.load(f.queue)
        from ges_next.pipeline.transfer import acquire
        step=plan['steps'][1];package=runner.package_for(f.queue,step['utc'],plan)
        journal=runner.journal_for(package)
        try:journal.create_job(package,runner.h9_profile(95,1000))
        finally:journal.close()
        acquire(step,package,None,f.client,lambda value:None)
        f.produce(step,package,f.project['Production'])
        original=f.produce;recovered=threading.Event()
        def verify(candidate):
            if candidate==package:recovered.set()
        def produce(item,candidate,profile):
            self.assertTrue(recovered.wait(30),'Committed recovery must start despite ready fresh work')
            original(item,candidate,profile)
        f.workers.verify=verify;f.workers.produce=produce
        self.assertEqual(self.run_parallel()['phase'],'complete')
        self.assertEqual(f.produced.count(step['utc']),1,'Recovery must not redo science')
        self.assertTrue((package/'cleanup_result.json').exists())

    def test_first_sample_still_blocks_prefetch(self):
        self.assertEqual(self.run_parallel()['phase'],'awaiting-quality');self.assertEqual(len(self.f.calls),60)

    def test_overlap_preserves_gates_cleanup_and_sequence_order(self):
        self.accept_first();f=self.f;original=f.produce;get=f.client.get_object
        lock=threading.Lock();active=0;peak=0;overlap=False;started=0;second_started=threading.Event()
        def produce(step,package,profile):
            nonlocal active,peak,started
            with lock:
                active+=1;peak=max(peak,active);started+=1;number=started
                if number==2:second_started.set()
            try:
                if number==1:self.assertTrue(second_started.wait(90),'Second producer must start while first occupies a slot')
                original(step,package,profile)
            finally:
                with lock:active-=1
        def download(**kwargs):
            nonlocal overlap
            with lock:overlap|=active>0
            time.sleep(.002);return get(**kwargs)
        f.workers.produce=produce;f.client.get_object=download
        state=self.run_parallel()
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),4)
        self.assertEqual(state['completed'],sorted(state['completed']));self.assertTrue(overlap);self.assertEqual(peak,2)
        self.assertEqual(list(f.queue.rglob('*.bz2')),[]);self.assertEqual(len(f.calls),240)
        for utc in state['completed']:
            p=runner.package_for(f.queue,utc);self.assertTrue((p/'blender_reopen.json').exists());self.assertTrue((p/'assets/base.jpg').exists())

    def test_failure_retains_failed_inputs_and_completed_siblings(self):
        self.accept_first();f=self.f;original=f.produce
        def produce(step,package,profile):
            if step['utc'].endswith('13:20:00Z'):raise ValueError('fixture failed scan')
            original(step,package,profile)
        f.workers.produce=produce
        with self.assertRaises(RuntimeError):self.run_parallel()
        state=json.loads((f.queue/'state.json').read_text());self.assertEqual(state['phase'],'failed-inputs-preserved')
        p=runner.package_for(f.queue,'2026-10-20T13:20:00Z');self.assertTrue(list(p.rglob('*.bz2')));self.assertFalse((p/'cleanup_result.json').exists())
        from ges_next.pipeline.transfer import cached
        objects={item['key']:item for step in json.loads((f.queue/'plan.json').read_text(encoding='utf-8'))['steps'] for item in step['objects']}
        verified=set()
        for path in f.queue.rglob('*.bz2'):
            receipt=json.loads(Path(str(path)+'.json').read_text()) if Path(str(path)+'.json').exists() else {}
            key=receipt.get('key')
            if key in objects and cached(path,objects[key]):verified.add(key)
        before=len(f.calls)
        f.workers.produce=original;self.assertEqual(self.run_parallel()['phase'],'complete')
        # Safe cancellation may interrupt up to four object streams. Only those
        # uncommitted partials may be re-fetched; verified inputs must be reused.
        self.assertFalse(verified.intersection(call['Key'] for call in f.calls[before:]))
        self.assertEqual(len({call['Key'] for call in f.calls}),240)

    def test_graceful_pause_and_resume(self):
        self.accept_first();f=self.f;original=f.produce;requested=False
        def produce(step,package,profile):
            nonlocal requested
            if not requested:requested=True;write_json(f.queue/'pause_requested.json',dict(requested=True))
            original(step,package,profile)
        f.workers.produce=produce
        self.assertEqual(self.run_parallel()['phase'],'paused-user')
        f.workers.produce=original;time.sleep(.02)
        self.assertEqual(self.run_parallel()['phase'],'complete')


if __name__=='__main__':unittest.main()
