import json,tempfile,unittest
from pathlib import Path
from ges_next.pipeline.workers import module
from unittest.mock import patch


class WorkerTelemetryTests(unittest.TestCase):
    def test_watchdog_collects_peak_memory_without_duplicate_tree_scan(self):
        from ges_next.pipeline.worker_watchdog import Watchdog
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'science_worker.log'
            with patch('ges_next.pipeline.stage_resources.tree_rss',side_effect=AssertionError('duplicate process-tree scan')):
                module('tests.worker_timing_fixture',[],Path.cwd(),log,lambda value:None,watchdog=Watchdog(5,10))
            timing=json.loads(log.with_suffix('.timing.json').read_text(encoding='utf-8'))
            self.assertEqual(timing['exit_code'],0);self.assertGreater(timing['peak_tree_rss_bytes'],0)

    def test_process_identity_and_phase_timings_survive_child_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'science_worker.log';events=[]
            module('tests.worker_timing_fixture',[],Path.cwd(),log,events.append)
            identity=json.loads(log.with_suffix('.process.json').read_text(encoding='utf-8'))
            timing=json.loads(log.with_suffix('.timing.json').read_text(encoding='utf-8'))
            self.assertGreater(identity['pid'],0);self.assertIsNotNone(identity['created'])
            self.assertEqual(timing['exit_code'],0)
            self.assertEqual([e['phase'] for e in timing['events']],['fixture-start','fixture-end'])
            self.assertGreater(timing['peak_tree_rss_bytes'],0)
            self.assertGreaterEqual(timing['seconds'],.2)


if __name__=='__main__':unittest.main()
