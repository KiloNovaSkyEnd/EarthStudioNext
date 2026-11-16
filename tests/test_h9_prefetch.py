"""A bounded download overlaps science without changing observation identity."""
from threading import Event
import unittest
from ges_next.h9_prefetch import OneScanPrefetch,next_pending_scene,GIB


def scene(utc):
    return dict(utc=utc,missing=[],objects=[dict(bytes=123)])


class PrefetchTests(unittest.TestCase):
    def test_one_producer_exact_time_waited_and_consumed_once(self):
        entered=Event();release=Event();calls=[];reports=[];budgets=[]
        def fetch(s):
            calls.append(s['utc']);entered.set()
            if not release.wait(3):raise RuntimeError('test did not release')
            return ['all validated source paths']
        with OneScanPrefetch(fetch,budgets.append,reports.append,enabled=True) as pipeline:
            self.assertTrue(pipeline.start(scene('next')))
            self.assertTrue(entered.wait(3))
            self.assertFalse(pipeline.future.done())
            with self.assertRaises(RuntimeError):pipeline.start(scene('other'))
            with self.assertRaises(ValueError):pipeline.take(scene('wrong UTC'))
            release.set()
            self.assertEqual(pipeline.take(scene('next')),['all validated source paths'])
            self.assertIsNone(pipeline.take(scene('next')))
        self.assertEqual(calls,['next'])
        self.assertEqual(budgets,[123+4*GIB])
        self.assertEqual([r['state'] for r in reports],['downloading','ready','consumed'])

    def test_failure_propagates_before_decoding_and_pool_drains(self):
        reports=[];finished=Event()
        def failed(s):
            finished.set();raise ValueError('ETag/integrity failed')
        with OneScanPrefetch(failed,lambda n:None,reports.append,True) as pipeline:
            pipeline.start(scene('next'))
            with self.assertRaisesRegex(ValueError,'integrity'):pipeline.take(scene('next'))
        self.assertTrue(finished.is_set())
        self.assertEqual(reports[-1]['state'],'failed')

    def test_storage_denial_and_disabled_mode_never_fetch(self):
        calls=[];reports=[]
        def deny(n):raise RuntimeError('reserve')
        with OneScanPrefetch(calls.append,deny,reports.append,True) as pipeline:
            self.assertFalse(pipeline.start(scene('next')))
            self.assertIsNone(pipeline.take(scene('next')))
        self.assertEqual(calls,[])
        self.assertEqual(reports[-1]['state'],'deferred_storage')
        with OneScanPrefetch(calls.append,deny,reports.append,False) as pipeline:
            self.assertFalse(pipeline.start(scene('next')))
        self.assertEqual(calls,[])

    def test_next_scan_skips_explicit_gaps_and_committed_frames(self):
        scenes=[scene('current'),scene('gap'),scene('done'),scene('next')]
        scenes[1]['missing']=['provider missing']
        self.assertEqual(next_pending_scene(scenes,1,lambda s:s['utc']=='done')['utc'],'next')
        self.assertIsNone(next_pending_scene(scenes,4,lambda s:False))
