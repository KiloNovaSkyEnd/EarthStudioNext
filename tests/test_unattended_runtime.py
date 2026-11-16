"""Small fault injection proves retries do not bypass any per-frame gates."""
import json,os,tempfile,threading,time,unittest,uuid
from pathlib import Path
from unittest.mock import Mock,patch
import psutil
from tests import test_parallel_pipeline as fixtures
from ges_next.pipeline import parallel,workers,retry_book
from ges_next.pipeline.worker_watchdog import Watchdog,WorkerStalledError,stop_owned_tree
from ges_next.production.assets import write_json

class FrameRetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ParallelPipelineTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups);self.fixture.accept_first();self.f=self.fixture.f
        write_json(self.f.queue/'unattended.json',dict(enabled=True))
        for name in ('SHORT_DELAY','MAX_DELAY','REVIEW_DELAY'):
            p=patch.object(retry_book,name,.05);p.start();self.addCleanup(p.stop)
    def run_queue(self,report=lambda _:None):
        timer=threading.Timer(180,lambda:write_json(self.f.queue/'pause_requested.json',dict(fixture_timeout=True)))
        timer.start();self.addCleanup(timer.cancel)
        with patch.object(parallel,'capacity',return_value=2),patch('ges_next.pipeline.concurrency.Concurrency.admit',return_value=True):
            return parallel.run(self.f.queue,self.f.client,self.f.workers,max_compute=2,prefetch=2,report=report)
    def test_one_frame_transient_failure_retries_without_global_stop(self):
        original=self.f.produce;attempts=[]
        def produce(step,package,profile):
            if step['utc'].endswith('13:10:00Z'):
                attempts.append(True)
                if len(attempts)==1:raise RuntimeError('fixture worker unexpectedly exited')
            original(step,package,profile)
        self.f.workers.produce=produce
        state=self.run_queue();self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),4);self.assertEqual(len(attempts),2)
        self.assertEqual(json.loads((self.f.queue/'frame_retries.json').read_text())['frames'],{})
    def test_quality_error_is_retained_while_siblings_finish_and_user_pause_is_honored(self):
        original=self.f.produce
        def produce(step,package,profile):
            if step['utc'].endswith('13:10:00Z'):raise ValueError('quality mismatch; never approve fixture')
            original(step,package,profile)
        self.f.workers.produce=produce
        def report(value):
            if len(value.get('completed',[]))>=3:write_json(self.f.queue/'pause_requested.json',dict(user_requested=True))
        state=self.run_queue(report);self.assertEqual(state['phase'],'paused-user');self.assertEqual(len(state['completed']),3)
        failed=self.f.queue/'steps/20261020T131000Z';self.assertTrue(list(failed.rglob('*.bz2')));self.assertFalse((failed/'cleanup_result.json').exists())
        rows=json.loads((self.f.queue/'frame_retries.json').read_text())['frames'];self.assertTrue(rows['2026-10-20T13:10:00Z']['requires_attention'])
        self.f.workers.produce=original;time.sleep(.06)
        state=self.run_queue();self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),4)
    def test_cleanup_busy_retries_existing_commit_without_reproduction(self):
        from ges_next.production.retention import Retention
        original=Retention.execute;attempts=[]
        def clean(retention,plan):
            if plan['utc'].endswith('13:10:00Z'):
                attempts.append(True)
                if len(attempts)==1:
                    error=PermissionError('fixture sharing conflict');error.winerror=32;raise error
            return original(retention,plan)
        with patch.object(Retention,'execute',clean):state=self.run_queue()
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(attempts),2)
        self.assertEqual(self.f.produced.count('2026-10-20T13:10:00Z'),1)
    def test_retry_state_outside_frozen_plan_is_rejected(self):
        write_json(self.f.queue/'frame_retries.json',dict(schema='earthstudio.frame_retries.v1',frames={'wrong':dict(utc='wrong',attempt=1,next_unix=0)}))
        with self.assertRaises(ValueError):retry_book.RetryBook(self.f.queue,['known'])

class WatchdogTests(unittest.TestCase):
    def test_monitor_IO_and_CPU_do_not_hide_frozen_compute_counter(self):
        guard=Watchdog(10,100,now=0);guard.observe(1,tasks=5)
        self.assertIsNone(guard.observe(5,tasks=5,io=10**10,cpu=500))
        self.assertIn('no scientific',guard.observe(11,tasks=5,io=20**10,cpu=1000))
    def test_genuine_compute_progress_resets_stall_but_not_absolute_limit(self):
        guard=Watchdog(10,25,now=0)
        for t in (5,10,15,20):self.assertIsNone(guard.observe(t,tasks=t))
        self.assertIn('wall-clock',guard.observe(25,tasks=25))
    def test_PID_reuse_never_kills_unrelated_process(self):
        process=Mock(pid=1234);other=Mock();other.create_time.return_value=99
        with patch('ges_next.pipeline.worker_watchdog.psutil.Process',return_value=other):self.assertFalse(stop_owned_tree(process,10))
        process.kill.assert_not_called();other.kill.assert_not_called()
    def run_fixture(self,mode,guard):
        root=(Path('reports/unattended_worker_fixtures')/uuid.uuid4().hex).resolve();root.mkdir(parents=True)
        marker=root/'marker.txt'
        return root,marker,lambda:workers.module('reports.unattended_runtime_20261026.worker_fixture',[marker,mode],Path.cwd(),root/'worker.log',lambda _:None,watchdog=guard)
    def test_real_owned_stalled_child_stops_and_marker_is_retained(self):
        root,marker,run=self.run_fixture('stalled',Watchdog(1,8))
        with self.assertRaises(WorkerStalledError):run()
        self.assertTrue(marker.exists());self.assertTrue(json.loads((root/'worker.timing.json').read_text())['watchdog_reason'])
    def test_real_progress_child_finishes_normally(self):
        root,marker,run=self.run_fixture('progress',Watchdog(2,10));run()
        self.assertEqual(json.loads((root/'worker.timing.json').read_text())['exit_code'],0)
    def test_exited_launcher_cannot_leave_observed_sleep_descendant(self):
        root,marker,run=self.run_fixture('orphan',Watchdog(20,30))
        try:
            with self.assertRaises((WorkerStalledError,RuntimeError)):run()
            pid=int(marker.with_suffix('.pid').read_text())
            try:psutil.Process(pid).wait(timeout=5)
            except psutil.NoSuchProcess:pass
        finally:
            if marker.with_suffix('.pid').exists():
                try:psutil.Process(int(marker.with_suffix('.pid').read_text())).kill()
                except psutil.NoSuchProcess:pass

if __name__=='__main__':unittest.main()
