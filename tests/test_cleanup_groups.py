import json,os,unittest
from unittest.mock import patch
from tests.test_production_retention import RetentionTests,UTC


class CleanupGroupsTests(unittest.TestCase):
    def setUp(self):
        self.f=RetentionTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        f=self.f
        for i in range(16):
            p=f.package/'scratch'/f'part{i}.bin';p.parent.mkdir(exist_ok=True);p.write_bytes(b'owned fixture')
            f.j.register_input(f.job,UTC,p,'temporary')
        f.accepted()

    def test_all_intents_are_durable_before_deletion_and_fewer_syncs(self):
        f=self.f;plan=f.r.plan(f.job,UTC);sync=os.fsync;calls=[]
        from ges_next.production.owned_files import delete_verified
        def barrier(handle):sync(handle);calls.append('sync')
        def deletion(path,stamp):
            intents=[json.loads(l) for l in (f.package/'cleanup_intents.jsonl').read_text().splitlines()]
            self.assertIn(str(path),[r['path'] for r in intents]);self.assertTrue(calls)
            delete_verified(path,stamp)
        with patch('ges_next.production.retention.os.fsync',side_effect=barrier),patch('ges_next.production.retention.delete_verified',side_effect=deletion):
            result=f.r.execute(plan)
        self.assertEqual(result['deleted_files'],17);self.assertEqual(len(calls),2)

    def test_crash_mid_group_recovers_only_absent_owned_files(self):
        f=self.f
        from ges_next.production.owned_files import delete_verified
        calls=[]
        def crash(path,stamp):
            delete_verified(path,stamp);calls.append(str(path))
            if len(calls)==3:raise RuntimeError('simulated crash')
        with patch('ges_next.production.retention.delete_verified',side_effect=crash):
            with self.assertRaises(RuntimeError):f.r.execute(f.r.plan(f.job,UTC))
        self.assertEqual(len((f.package/'cleanup_intents.jsonl').read_text().splitlines()),16)
        remaining=f.r.plan(f.job,UTC)
        self.assertEqual(len(remaining['candidates']),14)
        self.assertEqual(f.r.execute(remaining)['deleted_files'],14)
