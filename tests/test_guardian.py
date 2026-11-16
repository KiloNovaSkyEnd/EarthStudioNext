"""Guardian intent tests never launch production or terminate real workers."""
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from ges_next.pipeline import guardian

class GuardianIntentTests(unittest.TestCase):
    def test_safe_pause_wins_even_while_engine_drains(self):
        self.assertEqual(guardian.decision('parallel-running',busy=True,explicit_pause=True),'user-paused')
    def test_immediate_cancel_with_desktop_alive_is_not_undone(self):
        self.assertEqual(guardian.decision('parallel-running',cancelled=True,ui_alive=True),'user-paused')
    def test_window_close_can_recover_after_desktop_exits(self):
        self.assertEqual(guardian.decision('parallel-running',cancelled=True,ui_alive=False),'recover')
    def test_crash_can_recover_with_desktop_still_present(self):
        self.assertEqual(guardian.decision('failed-inputs-preserved',ui_alive=True),'recover')
    def test_user_pause_remains_disarmed_across_guardian_restart(self):
        self.assertEqual(guardian.decision('parallel-running',armed=False),'user-paused')
    def test_quality_and_missing_decisions_are_never_approved(self):
        for phase in ('complete','awaiting-quality','awaiting-missing-decision'):
            self.assertEqual(guardian.decision(phase),'idle')
    def test_existing_owner_prevents_duplicate_launch(self):
        self.assertEqual(guardian.decision('parallel-running',busy=True),'watching')
    def test_process_matching_is_bound_to_module_queue_and_action(self):
        queue=Path('reports/guardian_fixture_queue').resolve()
        self.assertTrue(guardian.matches(['python','-m','ges_next.pipeline.cli','run','--queue',str(queue)],queue))
        self.assertFalse(guardian.matches(['python','-m','ges_next.production','run','--queue',str(queue)],queue))
        self.assertFalse(guardian.matches(['python','-m','ges_next.pipeline.cli','plan','--queue',str(queue)],queue))
        self.assertFalse(guardian.matches(['python','-m','ges_next.pipeline.cli','run','--queue',str(queue/'other')],queue))
    def test_pid_reuse_is_not_an_alive_desktop(self):
        p=Mock();p.create_time.return_value=22
        with patch.object(guardian.psutil,'Process',return_value=p):self.assertFalse(guardian.alive(1234,11))
    def test_bootstrap_is_hidden_and_does_not_inherit_desktop_output_pipes(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=Path.cwd()/'reports') as root,patch.object(guardian.subprocess,'Popen') as launch:
            launch.return_value.pid=1234;guardian.bootstrap(Path(root))
            args,kwargs=launch.call_args
            self.assertTrue(kwargs['close_fds']);self.assertEqual(kwargs['stdin'],guardian.subprocess.DEVNULL)
            self.assertIsNotNone(kwargs['stdout']);self.assertTrue(kwargs['creationflags']&getattr(guardian.subprocess,'CREATE_NO_WINDOW',0)==getattr(guardian.subprocess,'CREATE_NO_WINDOW',0))
    def test_cancel_exit_normalizes_windows_signed_and_unsigned_codes(self):
        self.assertTrue(guardian.cancelled_exit(-1));self.assertTrue(guardian.cancelled_exit(4294967295));self.assertFalse(guardian.cancelled_exit(1))
    def test_valid_engine_receipt_avoids_process_inventory(self):
        import json,tempfile
        with tempfile.TemporaryDirectory(dir=Path.cwd()/'reports') as root:
            queue=Path(root).resolve();(queue/'engine_owner.json').write_text(json.dumps(dict(pid=1234,created=10)))
            p=Mock();p.create_time.return_value=10;p.cmdline.return_value=['python','-m','ges_next.pipeline.cli','run','--queue',str(queue)]
            with patch.object(guardian.psutil,'Process',return_value=p),patch.object(guardian.psutil,'process_iter',side_effect=AssertionError('No broad process scan')):
                self.assertIs(guardian.discover(queue),p)
    def test_new_continue_is_not_disarmed_by_previous_paused_snapshot(self):
        from datetime import datetime,timezone
        state=dict(phase='paused-user',updated_utc=datetime.fromtimestamp(10,timezone.utc).isoformat())
        phase,explicit,_=guardian.pause_context(state,9,engine_created=20,engine_alive=True)
        self.assertEqual(phase,'checking-completed');self.assertFalse(explicit)
        self.assertEqual(guardian.decision(phase,busy=True),'watching')
    def test_current_engine_user_pause_stays_effective(self):
        state=dict(phase='parallel-running',updated_utc='2026-10-26T10:00:00+00:00')
        phase,explicit,_=guardian.pause_context(state,30,engine_created=20,engine_alive=True)
        self.assertTrue(explicit);self.assertEqual(guardian.decision(phase,busy=True,explicit_pause=explicit),'user-paused')
    def test_paused_idle_queue_does_not_scan_other_processes(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=Path.cwd()/'reports') as root,patch.object(guardian.psutil,'process_iter',side_effect=AssertionError('No idle process scan')):
            self.assertIsNone(guardian.discover(Path(root),scan=False))

if __name__=='__main__':unittest.main()
