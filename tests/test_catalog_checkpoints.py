import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ges.native_bridge import scan
from ges_next.production.atomic_json import write_json

class CatalogCheckpointTests(unittest.TestCase):
    project=dict(Id='checkpoint-fixture',StartUtc='2020-10-29T16:00:00Z',EndUtc='2020-10-29T17:00:00Z',IntervalMinutes=30)
    @staticmethod
    def query(when,choices,client):return dict(state='missing',source=choices[0])
    def test_batched_checkpoints_keep_every_record_and_exact_final_status(self):
        sizes=[]
        def publish(path,body):sizes.append(len(body['records']));write_json(path,body)
        with tempfile.TemporaryDirectory() as root,contextlib.redirect_stdout(io.StringIO()):
            path=scan(self.project,Path(root)/'catalog',self.query,object(),checkpoint_every=5,publish_fn=publish)
            body=json.loads(Path(path).read_text(encoding='utf-8'))
            self.assertEqual(sizes,[1,5,10,15]);self.assertEqual(len(body['records']),15);self.assertTrue(body['finished'])
    def test_interruption_flushes_uncheckpointed_records_without_claiming_complete(self):
        calls=[]
        def query(when,choices,client):
            if len(calls)==7:raise KeyboardInterrupt()
            calls.append(when);return self.query(when,choices,client)
        with tempfile.TemporaryDirectory() as root,contextlib.redirect_stdout(io.StringIO()):
            folder=Path(root)/'partial'
            with self.assertRaises(KeyboardInterrupt):scan(self.project,folder,query,object(),checkpoint_every=5,publish_fn=write_json)
            body=json.loads((folder/'inventory.json').read_text(encoding='utf-8'))
            self.assertEqual(len(body['records']),7);self.assertFalse(body['finished'])
    def test_transient_windows_reader_lock_does_not_abort_catalog(self):
        original=Path.replace;blocked=[]
        def replace(path,target):
            if Path(target).name=='inventory.json' and not blocked:
                blocked.append(True);error=OSError('fixture sharing violation');error.winerror=32;raise error
            return original(path,target)
        with tempfile.TemporaryDirectory() as root,contextlib.redirect_stdout(io.StringIO()),patch.object(Path,'replace',replace):
            path=scan(self.project,Path(root)/'catalog',self.query,object(),checkpoint_every=5,publish_fn=write_json)
            self.assertTrue(json.loads(Path(path).read_text(encoding='utf-8'))['finished']);self.assertEqual(blocked,[True])
