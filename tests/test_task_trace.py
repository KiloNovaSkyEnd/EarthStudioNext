import unittest
from dask import delayed,compute
from ges_next.performance.task_trace import TaskTrace,group


class TaskTraceTests(unittest.TestCase):
    def test_results_unchanged_and_task_counts_recorded(self):
        def step(x):return x+1
        with TaskTrace() as trace:result=compute(*[delayed(step)(i) for i in range(5)],scheduler='threads',num_workers=2)
        self.assertEqual(result,tuple(range(1,6)))
        report=trace.summary();self.assertEqual(sum(g['calls'] for g in report['groups']),5)
        self.assertTrue(all(g['task_elapsed_seconds']>=0 for g in report['groups']))
        self.assertFalse(report['graphs'][0]['errored'])
    def test_group_preserves_operation_name(self):
        self.assertEqual(group(('read-band-'+32*'a',0,1)),'read-band')
        self.assertEqual(group(('read-band-13',0,1)),'read-band-13')
