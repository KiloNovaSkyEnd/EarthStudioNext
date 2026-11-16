import os,types,unittest
from pathlib import Path
from unittest.mock import patch
from ges_next.performance.policy import settings


class WorkerBudgetTests(unittest.TestCase):
    def test_available_memory_does_not_needlessly_limit_two_scans_to_five_threads(self):
        with patch('psutil.virtual_memory',return_value=types.SimpleNamespace(available=14*1024**3)),\
             patch('os.cpu_count',return_value=20),\
             patch('ges_next.performance.policy.profile_path',return_value=Path('missing-fixture-profile')),\
             patch.dict(os.environ,EARTHSTUDIO_PARALLEL_SLOTS='2'):
            two=settings();self.assertEqual(two['compute_workers'],8);self.assertEqual(two['decode_workers'],4)
            with patch.dict(os.environ,EARTHSTUDIO_PARALLEL_SLOTS='5'):
                self.assertEqual(settings()['compute_workers'],4)

    def test_explicit_qualified_thread_counts_override_the_generic_guess(self):
        with patch.dict(os.environ,EARTHSTUDIO_PARALLEL_SLOTS='3',EARTHSTUDIO_COMPUTE_THREADS='4',EARTHSTUDIO_DECODE_THREADS='4'):
            result=settings();self.assertEqual(result['compute_workers'],4);self.assertEqual(result['decode_workers'],4)


if __name__=='__main__':unittest.main()
