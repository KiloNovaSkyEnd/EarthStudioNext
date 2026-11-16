import json,subprocess,sys,unittest
from tests.test_pipeline import PipelineTests
from ges_next.pipeline.locking import exclusive,QueueBusyError
from ges_next.pipeline import parallel


class QueueReconnectTests(unittest.TestCase):
    def setUp(self):
        self.fixture=PipelineTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_duplicate_parallel_run_never_marks_healthy_owner_failed(self):
        f=self.fixture;state=f.queue/'state.json';data=json.loads(state.read_text());data['phase']='parallel-running'
        state.write_text(json.dumps(data));before=state.read_bytes();failure=f.queue/'last_failure.json'
        failure.write_text('{"historical":"preserve"}');old=failure.read_bytes()
        with exclusive(f.queue/'queue.lock'):
            with self.assertRaises(QueueBusyError):parallel.run(f.queue,f.client,f.workers)
        self.assertEqual(state.read_bytes(),before);self.assertEqual(failure.read_bytes(),old)
        self.assertEqual(f.calls,[])

    def test_cli_duplicate_attaches_without_night_check_or_payload(self):
        f=self.fixture;state=f.queue/'state.json';before=state.read_bytes()
        with exclusive(f.queue/'queue.lock'):
            result=subprocess.run([sys.executable,'-X','utf8','-m','ges_next.pipeline.cli','run','--queue',str(f.queue)],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['phase'],'queue-already-running')
        self.assertEqual(state.read_bytes(),before)
        self.assertFalse((f.queue/'last_failure.json').exists())

    def test_lock_released_after_owner_exits(self):
        f=self.fixture
        code="from ges_next.pipeline.locking import exclusive;from pathlib import Path;import sys;\nwith exclusive(Path(sys.argv[1])):\n print('READY',flush=True);sys.stdin.read()"
        # Bypass Windows venv launcher so kill() targets the actual lock owner.
        child=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-u','-c',code,str(f.queue/'queue.lock')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'READY')
            with self.assertRaises(QueueBusyError):
                with exclusive(f.queue/'queue.lock'):pass
        finally:child.kill();child.wait();child.stdin.close();child.stdout.close()
        with exclusive(f.queue/'queue.lock'):pass
