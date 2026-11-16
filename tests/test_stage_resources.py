import tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from ges_next.pipeline.stage_resources import can_start_science,tree_rss,live_rss
from ges_next.pipeline.admission import GIB
from ges_next.production.assets import write_json


class StageBudgetTests(unittest.TestCase):
    def test_verification_uses_its_live_memory_not_stale_science_rss(self):
        tasks=[dict(package=Path('science'),phase='producing'),dict(package=Path('verify'),phase='verifying')]
        with patch('ges_next.pipeline.stage_resources.live_rss',side_effect=lambda p,r:4*GIB if r=='science' else GIB):
            self.assertTrue(can_start_science(tasks,6*GIB,2*GIB,available=13*GIB))
            self.assertFalse(can_start_science(tasks,6*GIB,2*GIB,available=12*GIB))

    def test_cleaning_does_not_keep_a_full_science_reservation(self):
        with patch('ges_next.pipeline.stage_resources.live_rss',return_value=0):
            self.assertTrue(can_start_science([dict(package='job',phase='cleaning')],6*GIB,2*GIB,available=10*GIB))
            self.assertFalse(can_start_science([dict(package='job',phase='producing')],6*GIB,2*GIB,available=15*GIB))

    def test_waiting_verifiers_reserve_one_serial_verification_budget(self):
        tasks=[dict(package=f'job{i}',phase='waiting-verification') for i in range(3)]
        with patch('ges_next.pipeline.stage_resources.live_rss',return_value=0):
            self.assertTrue(can_start_science(tasks,6*GIB,2*GIB,available=12*GIB))

    def test_reused_pid_is_not_credited_as_task_memory(self):
        fake=types.SimpleNamespace(create_time=lambda:20)
        with patch('psutil.Process',return_value=fake):self.assertEqual(tree_rss(123,10),0)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);write_json(root/'science_worker.process.json',dict(pid=123,created=None))
            self.assertEqual(live_rss(root,'science'),0)

    def test_asset_verification_does_not_reserve_a_nonexistent_blender(self):
        tasks=[dict(package='job',phase='verifying-assets')]
        self.assertTrue(can_start_science(tasks,5*GIB,7*GIB,available=11*GIB))
        self.assertFalse(can_start_science(tasks,5*GIB,7*GIB,available=10*GIB))


if __name__=='__main__':unittest.main()
