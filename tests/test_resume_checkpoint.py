"""Tiny mocked journal checks make real resume progress visible to the guardian."""
import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import MagicMock,patch
from ges_next.pipeline import parallel

class ResumeCheckpointTests(unittest.TestCase):
    def test_25_checked_frames_are_persisted_without_reprocessing(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()/'reports') as folder:
            root=Path(folder).resolve();times=[(datetime(2026,10,12,tzinfo=timezone.utc)+timedelta(minutes=10*n)).isoformat().replace('+00:00','Z') for n in range(25)]
            plan=dict(missing_nodes=0,project=dict(Production=dict(JpegQuality=95,NightLightMetres=1000)),steps=[dict(utc=s) for s in times],nodes=[])
            state=dict(phase='complete',completed=times.copy());journal=MagicMock();journal.db.execute.return_value.fetchone.return_value=dict(id='owned-fixture')
            worker=MagicMock();events=[]
            with patch.object(parallel.runner,'load',return_value=(root,plan,state)),patch.object(parallel.runner,'accepted',return_value=True),patch.object(parallel.runner,'package_for',side_effect=lambda r,u,p=None:r/'steps'/u.replace(':','')),patch.object(parallel.runner,'journal_for',return_value=journal),patch.object(parallel,'capacity',return_value=2),patch.object(parallel,'Concurrency'):
                result=parallel.run(root,None,worker,report=events.append,max_compute=2,prefetch=2)
            self.assertEqual(result['phase'],'complete');self.assertEqual(result['checked_completed'],25)
            self.assertEqual(journal.gate.call_count,25);worker.produce.assert_not_called()
            persisted=[json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
            self.assertTrue(any(v['phase']=='checking-completed' for v in persisted));self.assertTrue(any(v.get('checked_completed')==25 for v in events))
