"""Pressure admission and actual telemetry; no large inputs or network."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import unittest
from ges.earth_validation.resources import page_workers,monitor,GIB


class ResourceTests(unittest.TestCase):
    def test_page_admission_under_system_memory_pressure(self):
        for free, expected in ((3*GIB,1),(6*GIB,1),(7*GIB,2),(10*GIB,4)):
            with self.subTest(free=free), patch('psutil.virtual_memory',return_value=SimpleNamespace(available=free)):
                self.assertEqual(page_workers(),expected)

    def test_monitor_writes_actual_process_and_stops(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            with monitor(root):
                # Join uses a short event wait, not an expensive processing job.
                import time
                deadline=time.monotonic()+3
                while not (root/'reports/resource_usage.json').exists() and time.monotonic()<deadline:
                    time.sleep(.01)
            record=json.loads((root/'reports/resource_usage.json').read_text())
            self.assertGreater(record['pid'],0)
            self.assertGreater(record['process_rss_bytes'],0)
            self.assertGreater(record['system_total_bytes'],0)
