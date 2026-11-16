"""Offline desktop integration: real Qt subprocesses, no satellite downloads."""
import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from ges.desktop.jobs import Job
from ges.desktop.runner import TaskRunner
from ges.desktop.worker import execute

APP = QApplication.instance() or QApplication([])


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='earth studio 中文 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def texture(self, name, pixel):
        path = self.root / name
        image = Image.new('RGBA', (4, 2), (0, 0, 0, 0))
        image.putpixel(pixel, (60, 60, 60, 255))
        image.save(path)
        path.with_suffix('.json').write_text(json.dumps({
            'projection': 'EPSG:4326', 'extent_wsen': [-180, -90, 180, 90],
            'width': 4, 'height': 2, 'product': 'ir-gray',
            'source_satellite': 'himawari8', 'observed_utc': '2020-10-29T16:40:00Z'}), encoding='utf-8')
        return path

    def run_job(self, job, executable=sys.executable):
        runner = TaskRunner()
        loop = QEventLoop()
        results, logs, ticks = [], [], []
        runner.completed.connect(lambda status, result: (results.append((status, result)), loop.quit()))
        runner.output.connect(logs.append)
        heartbeat = QTimer()
        heartbeat.timeout.connect(lambda: ticks.append(1))
        heartbeat.start(5)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(20000)
        runner.start(job, executable)
        if not results:
            loop.exec()
        timeout.stop()
        heartbeat.stop()
        if runner.busy:
            runner.cancel()
            cleanup = QEventLoop()
            runner.completed.connect(cleanup.quit)
            QTimer.singleShot(5000, cleanup.quit)
            cleanup.exec()
        self.assertTrue(results, 'task timed out')
        return results[0], ''.join(logs), ticks

    def test_unique_outputs_and_unicode_subprocess_mosaic(self):
        a, b = self.texture('甲.png', (0, 0)), self.texture('乙.png', (1, 0))
        options = {'images': [str(a), str(b)], 'utc': '2020-10-29T16:40:00Z'}
        job = Job.create('mosaic', options, self.root)
        second = Job.create('mosaic', options, self.root)
        self.assertNotEqual(job.directory, second.directory)
        before = a.read_bytes()
        (status, result), logs, ticks = self.run_job(job)
        self.assertEqual(status, 'succeeded', logs)
        self.assertGreater(len(ticks), 0, 'UI event loop must remain responsive')
        self.assertEqual(a.read_bytes(), before)
        with Image.open(result) as image:
            self.assertEqual(image.getpixel((0, 0))[3], 255)
            self.assertEqual(image.getpixel((1, 0))[3], 255)
            self.assertEqual(image.getpixel((2, 0))[3], 0)
        record = json.loads((job.directory / 'job.json').read_text(encoding='utf-8'))
        self.assertEqual(record['status'], 'succeeded')
        self.assertIn('完成', (job.directory / 'task.log').read_text(encoding='utf-8'))

    def test_failure_is_logged_and_persisted(self):
        job = Job.create('render', {'manifest': 'missing.json', 'product': 'ir-gray', 'width': 2048}, self.root)
        (status, result), logs, _ = self.run_job(job)
        self.assertEqual((status, result), ('failed', ''))
        self.assertIn('Traceback', logs)
        self.assertEqual(json.loads((job.directory / 'job.json').read_text())['status'], 'failed')

    def test_missing_executable_releases_runner(self):
        job = Job.create('search', {}, self.root)
        (status, result), _, _ = self.run_job(job, str(self.root / 'missing.exe'))
        self.assertEqual(status, 'failed')

    def test_cancellation_preserves_files_and_stops_child(self):
        child_pid_file = self.root / 'child.pid'
        code = ('import subprocess,sys,time,pathlib; '
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"]); '
                f'pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid)); '
                'print("ready",flush=True); time.sleep(120)')
        job = Job.create('search', {}, self.root)
        runner = TaskRunner()
        loop = QEventLoop()
        statuses = []
        runner.completed.connect(lambda status, result: (statuses.append(status), loop.quit()))
        runner.output.connect(lambda text: runner.cancel() if 'ready' in text else None)
        with patch.object(Job, 'command', return_value=(sys.executable, ['-u', '-c', code])):
            runner.start(job, sys.executable)
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
        if runner.busy:
            runner.process.kill()
            runner.process.waitForFinished(5000)
        self.assertEqual(statuses, ['cancelled'])
        self.assertTrue((job.directory / 'task.log').is_file())
        self.assertEqual(json.loads((job.directory / 'job.json').read_text())['status'], 'cancelled')
        if os.name == 'nt':
            import ctypes
            pid = int(child_pid_file.read_text())
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(handle)
                self.assertNotEqual(exit_code.value, 259, 'Blender-like child still active')

    def test_daylight_adapter_uses_directory_and_propagates_result(self):
        job = Job.create('daylight', {}, self.root)
        expected = job.directory / 'daylight' / 'observed.png'
        with patch('ges.daylight.render_daylight', return_value=expected) as render:
            result = execute('daylight', {'manifest': 'source.json', 'width': 2048}, job.directory)
        self.assertEqual(result, expected)
        render.assert_called_once_with('source.json', job.directory / 'daylight', 2048)

    def test_window_forms_and_handoff(self):
        from ges.desktop.window import MainWindow
        window = MainWindow()
        self.addCleanup(window.close)
        self.assertEqual(window.tabs.count(), 6)
        window.finished('succeeded', str(self.root / 'scene.json'))
        self.assertEqual(window.processing.manifest.text(), str(self.root / 'scene.json'))
        png = self.texture('result.png', (0, 0))
        window.finished('succeeded', str(png))
        self.assertEqual(window.blender.image.text(), str(png))

    def test_batch_failure_keeps_completed_summary_and_inputs(self):
        job = Job.create('render-batch', {}, self.root)
        a = self.texture('source.png', (0, 0))
        before = a.read_bytes()
        product = job.directory / 'scene_0001' / 'result.png'
        with patch('ges.render.render', side_effect=[product, RuntimeError('bad second scene')]), \
                patch('sys.stdout', new_callable=io.StringIO) as progress:
            with self.assertRaisesRegex(RuntimeError, 'bad second'):
                execute('render-batch', {'manifests': ['first.json', 'second.json'],
                    'product': 'ir-gray', 'width': 2048}, job.directory)
        self.assertIn('2/2', progress.getvalue())
        summary = json.loads((job.directory / 'batch_results.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['total'], 2)
        self.assertEqual(summary['completed'], [{'manifest': 'first.json', 'path': str(product)}])
        self.assertEqual(a.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
