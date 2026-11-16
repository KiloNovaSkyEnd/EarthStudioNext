"""Windows reader contention and reporting failure cannot kill image compute."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from ges.earth_validation.project import save
from ges.earth_validation.compute_progress import ComputeProgress


class AtomicReportTests(unittest.TestCase):
    def test_transient_replace_denial_retries_and_keeps_valid_json(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'status.json'; save(path,{'value':1})
            original=Path.replace; attempts=[]
            def replace(source,target):
                attempts.append(source)
                if len(attempts)<3: raise PermissionError('Reader temporarily denies delete sharing')
                return original(source,target)
            with patch.object(Path,'replace',replace): save(path,{'value':2})
            self.assertEqual(json.loads(path.read_text())['value'],2)
            self.assertEqual(len(attempts),3)

    def test_concurrent_writers_do_not_share_temporary_paths(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'status.json'
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda n:save(path,{'value':n}),range(12)))
            self.assertIn(json.loads(path.read_text())['value'],range(12))
            self.assertFalse(list(Path(temporary).glob('*.tmp')))

    def test_unwritable_progress_does_not_abort_dask_callback(self):
        progress=ComputeProgress(Path('unused'),'fixture')
        with patch('ges.earth_validation.project.save',side_effect=PermissionError('locked')):
            progress._start({'task':1})
            progress._posttask('task',None,None,None,None)
            progress._finish(None,None,False)
        self.assertEqual(progress.done,1)
