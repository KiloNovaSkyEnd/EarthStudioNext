import tempfile,unittest
from collections import deque
from pathlib import Path
from ges_next.pipeline.parallel import take_pending,take_ready


class RecoveryFairnessTests(unittest.TestCase):
    def test_full_prefetch_still_admits_one_payload_free_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fresh=dict(utc='2026-10-24T01:00:00Z');old=dict(utc='2026-10-24T00:00:00Z')
            p=root/'steps'/'20261024T000000Z';p.mkdir(parents=True);(p/'commit.json').write_text('{}')
            pending=deque([fresh,old])
            self.assertEqual(take_pending(pending,root,{},False,False),old)
            self.assertIsNone(take_pending(pending,root,{},True,False))
            self.assertIsNone(take_pending(pending,root,{},False,False))
            self.assertEqual(list(pending),[fresh])
            self.assertEqual(take_pending(pending,root,{},True,True),fresh)

    def test_recovery_starts_at_full_science_target_then_leaves_fresh_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fresh=(dict(utc='fresh'),root/'fresh','job-fresh')
            recover=(dict(utc='recover'),root/'recover','job-recover')
            recover[1].mkdir();(recover[1]/'commit.json').write_text('{}')
            ready=deque([fresh,recover])
            self.assertEqual(take_ready(ready,False,False),recover)
            self.assertIsNone(take_ready(ready,True,False))
            self.assertEqual(take_ready(ready,True,True),fresh)

    def test_recovery_is_bounded_to_one_and_does_not_launch_extra_science(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rows=[]
            for i in range(2):
                p=root/str(i);p.mkdir();(p/'commit.json').write_text('{}');rows.append((dict(utc=str(i)),p,str(i)))
            ready=deque(rows)
            self.assertIsNone(take_ready(ready,True,True))
            self.assertEqual(list(ready),rows)
            self.assertEqual(take_ready(ready,False,False),rows[0])

    def test_recovery_backlog_leaves_fresh_work_available(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);steps=[dict(utc=f'2026-10-24T{i:02}:00:00Z') for i in range(8)]
            for step in steps[:5]:
                package=root/'steps'/step['utc'].replace('-','').replace(':','');package.mkdir(parents=True)
                (package/'commit.json').write_text('{}')
            pending=deque(steps)
            self.assertEqual(take_pending(pending,root,{},False),steps[0])
            for fresh in steps[5:]:
                self.assertEqual(take_pending(pending,root,{},True),fresh)
            self.assertIsNone(take_pending(pending,root,{},True))
            self.assertEqual(take_pending(pending,root,{},False),steps[1])
            self.assertEqual(list(pending),steps[2:5])

    def test_fresh_only_queue_still_advances(self):
        with tempfile.TemporaryDirectory() as folder:
            step=dict(utc='2026-10-24T00:00:00Z');pending=deque([step])
            self.assertEqual(take_pending(pending,Path(folder),{},False),step)
            self.assertIsNone(take_pending(pending,Path(folder),{},False))
