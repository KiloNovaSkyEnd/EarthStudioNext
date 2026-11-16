import json,os,tempfile,threading,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from ges_next.production.assets import write_json


class AtomicJsonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd()/'reports');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'status.json';write_json(self.path,{'old':True})

    def test_transient_windows_access_error_keeps_old_complete_document(self):
        original=Path.replace;calls=[]
        def replace(source,target):
            calls.append(source)
            if len(calls)<3:
                self.assertEqual(json.loads(target.read_text()),{'old':True})
                error=PermissionError('reader busy');error.winerror=5;raise error
            return original(source,target)
        with patch.object(Path,'replace',replace):write_json(self.path,{'new':True})
        self.assertEqual(json.loads(self.path.read_text()),{'new':True})
        self.assertEqual(len(calls),3)

    def test_unrelated_or_persistent_error_preserves_old_and_candidate(self):
        for code in (2,5):
            error=OSError('cannot publish');error.winerror=code
            with patch.object(Path,'replace',side_effect=error),patch('ges_next.production.atomic_json.time.monotonic',side_effect=[0,6]):
                with self.assertRaises(OSError):write_json(self.path,{'new':True})
            self.assertEqual(json.loads(self.path.read_text()),{'old':True})
        self.assertEqual(len(list(self.path.parent.glob('*.part'))),2)

    def test_concurrent_publishers_never_share_a_partial(self):
        def publish(number):
            for index in range(8):write_json(self.path,dict(writer=number,index=index,payload='x'*2000))
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(publish,range(4)))
        self.assertEqual(len(json.loads(self.path.read_text())['payload']),2000)
        self.assertEqual(list(self.path.parent.glob('*.part')),[])

    @unittest.skipUnless(os.name=='nt','Windows share-delete regression')
    def test_real_windows_reader_lock_is_retried_without_truncation(self):
        failed=threading.Event();original=Path.replace
        def replace(source,target):
            try:return original(source,target)
            except PermissionError:failed.set();raise
        with self.path.open('rb') as reader,patch.object(Path,'replace',replace),ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(write_json,self.path,{'new':True})
            try:
                self.assertTrue(failed.wait(2),'Expected real Windows reader sharing conflict')
                self.assertEqual(json.load(reader),{'old':True})
            finally:reader.close()
            future.result(timeout=3)
        self.assertEqual(json.loads(self.path.read_text()),{'new':True})


if __name__=='__main__':unittest.main()
