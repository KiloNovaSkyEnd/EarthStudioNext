"""Tiny owned fixtures; Windows transient locks must not bypass identity gates."""
import ctypes,os,threading,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from ges_next.production import owned_files as owned

class CleanupSharingTests(unittest.TestCase):
    def test_windows_real_reader_releases_and_cleanup_rechecks(self):
        if os.name!='nt':self.skipTest('Real Windows sharing semantics')
        root=(Path('reports/cleanup_sharing_fixtures')/uuid.uuid4().hex).resolve();root.mkdir(parents=True)
        path=root/'owned.bin';path.write_bytes(b'owned tiny fixture');expected=owned.snapshot(path)
        stream=path.open('rb');released=threading.Event()
        def release():time.sleep(.2);stream.close();released.set()
        t=threading.Thread(target=release);t.start()
        try:owned.delete_verified(path,expected)
        finally:t.join();stream.close()
        self.assertTrue(released.is_set());self.assertFalse(path.exists())

    def test_retry_revalidates_changed_file_and_retains_it(self):
        root=(Path('reports/cleanup_sharing_fixtures')/uuid.uuid4().hex).resolve();root.mkdir(parents=True)
        path=root/'changed.bin';path.write_bytes(b'original');expected=owned.snapshot(path);original=owned._delete_verified_once;calls=[]
        def conflict_then_changed(*args):
            calls.append(True)
            if len(calls)==1:
                path.write_bytes(b'different content')
                if os.name=='nt':raise ctypes.WinError(32)
                error=PermissionError('sharing');error.winerror=32;raise error
            return original(*args)
        with patch.object(owned,'_delete_verified_once',side_effect=conflict_then_changed),patch.object(owned.time,'sleep'):
            with self.assertRaises(ValueError):owned.delete_verified(path,expected)
        self.assertEqual(path.read_bytes(),b'different content');self.assertEqual(len(calls),2)

    def test_timeout_is_bounded_and_reports_path(self):
        error=ctypes.WinError(32) if os.name=='nt' else PermissionError('sharing')
        if os.name!='nt':error.winerror=32
        with patch.object(owned,'_delete_verified_once',side_effect=error),patch.object(owned.time,'monotonic',side_effect=[0,31]),patch.object(owned.time,'sleep') as sleep:
            with self.assertRaises(PermissionError) as failure:owned.delete_verified('owned_fixture.bin',{})
        self.assertIn('owned_fixture.bin',str(failure.exception));sleep.assert_not_called()

    def test_access_denied_and_identity_errors_are_never_retried(self):
        for error in (PermissionError('not a Windows sharing conflict'),ValueError('changed identity')):
            with patch.object(owned,'_delete_verified_once',side_effect=error) as attempt,patch.object(owned.time,'sleep') as sleep:
                with self.assertRaises(type(error)):owned.delete_verified('fixture',{})
                self.assertEqual(attempt.call_count,1);sleep.assert_not_called()

if __name__=='__main__':unittest.main()
