import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import psutil

spec = importlib.util.spec_from_file_location('native_handoff', Path(__file__).parents[1] /
                                            'scripts/continue_native_after_qualification.py')
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class NativeHandoffTests(unittest.TestCase):
    def fixture(self, root, success):
        (root / 'reports').mkdir()
        engine, blender = root / 'engine.exe', root / 'blender.exe'
        engine.touch(); blender.touch()
        metadata = root / 'metadata.json'
        metadata.write_text('{"observation_support_version":2}')
        (root / 'geo_color.tif').touch()
        (root / 'reports/full_native_memory_qualification.json').write_text(json.dumps(
            dict(success=success, native_shape=[22000, 22000], metadata=str(metadata))))
        return engine, blender

    def test_failed_qualification_never_starts_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); engine, blender = self.fixture(root, False)
            with patch.object(handoff.psutil, 'Process', side_effect=psutil.NoSuchProcess(123)), \
                    patch.object(handoff.subprocess, 'Popen') as start:
                with self.assertRaises(ValueError):
                    handoff.main(root, engine, blender, 123)
                start.assert_not_called()

    def test_waits_for_specific_qualifier_and_launches_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); engine, blender = self.fixture(root, True)
            qualifier = Mock(); qualifier.cmdline.return_value = ['python', 'qualify_full_native_memory.py']
            qualifier.create_time.return_value = 0
            child = Mock(pid=456); child.wait.return_value = 0
            with patch.object(handoff.psutil, 'Process', return_value=qualifier), \
                    patch.object(handoff.subprocess, 'Popen', return_value=child) as start, \
                    patch('builtins.print'):
                handoff.main(root, engine, blender, 123)
                qualifier.wait.assert_called_once()
                start.assert_called_once()
                self.assertIn('native-pipeline', start.call_args.args[0])
                child.wait.assert_called_once()

    def test_stale_success_cannot_restart_after_failed_new_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); engine, blender = self.fixture(root, True)
            qualifier = Mock(); qualifier.cmdline.return_value = ['python','qualify_full_native_memory.py']
            qualifier.create_time.return_value = (root/'reports/full_native_memory_qualification.json').stat().st_mtime+10
            with patch.object(handoff.psutil, 'Process', return_value=qualifier), \
                    patch.object(handoff.subprocess, 'Popen') as start, patch('builtins.print'):
                with self.assertRaisesRegex(ValueError,'stale'):
                    handoff.main(root,engine,blender,123)
                start.assert_not_called()

    def test_legacy_coverage_receipt_never_starts_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); engine,blender=self.fixture(root,True)
            (root/'metadata.json').write_text('{}')
            with patch.object(handoff.psutil,'Process',side_effect=psutil.NoSuchProcess(123)), \
                    patch.object(handoff.subprocess,'Popen') as start:
                with self.assertRaisesRegex(ValueError,'legacy'):
                    handoff.main(root,engine,blender,123)
                start.assert_not_called()

    def test_unrelated_pid_does_not_trigger_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); engine, blender = self.fixture(root, True)
            unrelated = Mock(); unrelated.cmdline.return_value = ['unrelated.exe']
            with patch.object(handoff.psutil, 'Process', return_value=unrelated), \
                    patch.object(handoff.subprocess, 'Popen') as start:
                with self.assertRaises(ValueError):
                    handoff.main(root, engine, blender, 123)
                unrelated.wait.assert_not_called(); start.assert_not_called()
