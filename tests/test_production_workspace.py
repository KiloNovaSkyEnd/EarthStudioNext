"""Real workspace setup must pass the bounded reserve to nested cache modules."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import types
import unittest
import uuid
from unittest.mock import patch
from ges_next.production.h9_job import run
from ges.earth_validation.project import check_disk


class WorkspaceTests(unittest.TestCase):
    def test_nested_static_cache_uses_selected_reserve(self):
        root=(Path('reports/workspace_fixtures')/uuid.uuid4().hex).resolve()
        with patch('shutil.disk_usage',return_value=types.SimpleNamespace(free=16*1024**3)), \
             patch('ges_next.production.h9_job.source_files',return_value=[]), \
             patch('ges_next.production.h9_job.decode',side_effect=RuntimeError('fixture stops before scientific I/O')), \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'fixture stops'):
                run(root/'readonly-source',root/'readonly-reference','2026-10-20T13:00:00Z',root/'job')
            for folder in (root/'job',root/'job/scratch',root/'job/scratch/work'):
                self.assertEqual(json.loads((folder/'project.json').read_text())['reserve_free_bytes'],8*1024**3)
                self.assertGreater(check_disk(folder,121000000),0)


if __name__=='__main__':unittest.main()
