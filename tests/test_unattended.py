import json,time,threading
import unittest
from unittest.mock import patch
from botocore.exceptions import EndpointConnectionError
from tests import test_parallel_pipeline as fixtures
from ges_next.pipeline import parallel,runner
from ges_next.pipeline.network_retry import retry
from ges_next.production.assets import write_json


class UnattendedTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ParallelPipelineTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups);self.fixture.accept_first()
        self.f=self.fixture.f;self.reports=[]

    def run_queue(self,report=None,capacity=lambda *a:2,admit=lambda *a:True):
        with patch('ges_next.pipeline.parallel.capacity',side_effect=capacity),\
             patch('ges_next.pipeline.concurrency.Concurrency.admit',side_effect=admit),\
             patch('ges_next.pipeline.transfer.retry',side_effect=lambda op,report,**kw:retry(op,report,sleep=lambda _:time.sleep(.002),**kw)):
            return parallel.run(self.f.queue,self.f.client,self.f.workers,max_compute=2,prefetch=2,
                report=report or self.reports.append)

    def offline(self):
        original=self.f.client.get_object
        def get(**kw):
            if '/1310/' in kw['Key']:raise EndpointConnectionError(endpoint_url='https://fixture.invalid')
            return original(**kw)
        self.f.client.get_object=get

    def test_other_ready_scan_finishes_during_outage_then_network_recovers(self):
        f=self.f;get=f.client.get_object;produce=f.produce;recovered=threading.Event();offline_seen=threading.Event();sibling=[]
        safety=threading.Timer(180,recovered.set);safety.start();self.addCleanup(safety.cancel)
        def client(**kw):
            if '/1310/' in kw['Key'] and not recovered.is_set():
                offline_seen.set();raise EndpointConnectionError(endpoint_url='https://fixture.invalid')
            return get(**kw)
        def work(step,package,profile):
            produce(step,package,profile)
            if step['utc'].endswith('13:20:00Z'):
                sibling.append(offline_seen.is_set() and not recovered.is_set());recovered.set()
        f.client.get_object=client;f.workers.produce=work
        state=self.run_queue()
        self.assertEqual(state['phase'],'complete');self.assertEqual(len(state['completed']),4)
        self.assertEqual(sibling,[True])
        events=[json.loads(line) for line in (f.queue/'events.jsonl').read_text().splitlines()]
        self.assertTrue(any(any(a['phase']=='waiting-network' for a in r.get('active',[])) for r in events))

    def test_pause_during_outage_does_not_record_failure(self):
        self.offline()
        def report(v):
            self.reports.append(v)
            if any(a['phase']=='waiting-network' for a in v.get('active',[])):
                write_json(self.f.queue/'pause_requested.json',dict(requested=True))
        state=self.run_queue(report)
        self.assertEqual(state['phase'],'paused-user');self.assertFalse((self.f.queue/'last_failure.json').exists())
        self.assertTrue(any(r.get('phase')=='parallel-running' for r in self.reports))

    def test_fatal_sibling_cancels_outage_wait_and_preserves_input(self):
        self.offline()
        def work(*a):raise ValueError('quality mismatch')
        self.f.workers.produce=work
        with self.assertRaises(RuntimeError):self.run_queue()
        state=json.loads((self.f.queue/'state.json').read_text())
        self.assertEqual(state['phase'],'failed-inputs-preserved')
        self.assertTrue(list(self.f.queue.rglob('*.bz2')))

    def test_memory_recovers_without_user_continue(self):
        calls=[]
        def admit(*a):calls.append(1);return len(calls)>3
        state=self.run_queue(admit=admit)
        self.assertEqual(state['phase'],'complete')
        self.assertTrue(any(v.get('waiting_reason')=='memory' for v in self.reports))

    def test_disk_recovers_without_user_continue(self):
        calls=[]
        def capacity(*a):calls.append(1);return 0 if len(calls)<4 else 2
        state=self.run_queue(capacity=capacity)
        self.assertEqual(state['phase'],'complete')
        self.assertTrue(any(v.get('waiting_reason')=='space' for v in self.reports))


if __name__=='__main__':unittest.main()
