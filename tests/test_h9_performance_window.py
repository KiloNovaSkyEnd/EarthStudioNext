from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from ges_next.h9_performance_window import wait_for_window


class PerformanceWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.p=Path(self.temp.name);(self.p/'reports').mkdir()
        self.now=datetime(2026,10,23,tzinfo=timezone.utc)
        self.path=self.p/'reports/performance_window.json'
        self.control=dict(state='hold',utc='2026-10-20T20:50:00Z',token='test',
            created_utc=self.now.isoformat(),expires_utc=(self.now+timedelta(seconds=4)).isoformat())
        self.path.write_text(json.dumps(self.control))
    def run_window(self,**kwargs):
        wait_for_window(self.p,self.control['utc'],4,clock=lambda:self.now,**kwargs)
    def test_expires_even_if_research_controller_disappears(self):
        reports=[]
        def advance(seconds):self.now+=timedelta(seconds=seconds)
        self.run_window(sleep=advance,report=reports.append)
        self.assertEqual(len(reports),2)
    def test_release_and_other_scan_do_not_wait(self):
        def no_wait(seconds):self.fail('Unexpected wait')
        wait_for_window(self.p,'2026-10-20T21:00:00Z',4,sleep=no_wait)
        self.control['state']='released';self.path.write_text(json.dumps(self.control))
        self.run_window(sleep=no_wait)
    def test_scope_handoff_still_exits75(self):
        (self.p/'requested_scope.json').write_text(json.dumps(dict(generation=5)))
        with self.assertRaises(SystemExit) as raised:self.run_window()
        self.assertEqual(raised.exception.code,75)
    def test_unbounded_pause_rejected(self):
        self.control['expires_utc']=(self.now+timedelta(hours=2)).isoformat()
        self.path.write_text(json.dumps(self.control))
        with self.assertRaises(ValueError):self.run_window()
