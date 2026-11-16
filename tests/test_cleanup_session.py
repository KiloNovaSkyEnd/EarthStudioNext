"""Windows input hashes are reusable only while exact deletion handles pin them."""
import hashlib,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ges_next.production.owned_files import CleanupSession,snapshot,delete_verified


@unittest.skipUnless(os.name=='nt','Windows protected deletion handles')
class CleanupSessionTests(unittest.TestCase):
    def setUp(self):
        reports=(Path.cwd()/'reports').resolve()
        self.temp=tempfile.TemporaryDirectory(dir=reports)
        self.root=Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(reports));self.addCleanup(self.temp.cleanup)
        self.file=self.root/'owned.bin';self.file.write_bytes(b'full exact input bytes'*1000)

    def test_one_full_hash_two_plans_and_exact_handle_delete(self):
        with patch('hashlib.file_digest',wraps=hashlib.file_digest) as hashing:
            with CleanupSession() as session:
                expected=snapshot(self.file);self.assertEqual(snapshot(self.file),expected)
                delete_verified(self.file,expected)
                self.assertFalse(self.file.exists());self.assertEqual(hashing.call_count,1)
                self.assertEqual(session.protected_deletions,1);self.assertEqual(session.snapshot_hits,1)

    def test_writes_replacement_and_rename_blocked_until_session_exit(self):
        replacement=self.root/'replacement';replacement.write_bytes(b'new')
        with CleanupSession():
            snapshot(self.file)
            with self.assertRaises(PermissionError):self.file.write_bytes(b'changed')
            with self.assertRaises(PermissionError):replacement.replace(self.file)
            with self.assertRaises(PermissionError):self.file.rename(self.root/'moved')
        self.file.write_bytes(b'changed')

    def test_exception_releases_all_pins_and_does_not_cache_across_sessions(self):
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with CleanupSession():snapshot(self.file);raise RuntimeError('fixture')
        self.file.write_bytes(b'changed after failure')
        with CleanupSession() as session:
            expected=snapshot(self.file);self.assertEqual(session.hash_reads,1)
            self.assertEqual(expected['bytes'],len(b'changed after failure'))

    def test_changed_expected_identity_is_rejected_without_deletion(self):
        with CleanupSession():
            expected=snapshot(self.file);expected['sha256']='0'*64
            with self.assertRaises(ValueError):delete_verified(self.file,expected)
            self.assertTrue(self.file.exists())

    def test_unpinned_over_budget_file_retains_full_hash_checks(self):
        other=self.root/'other';other.write_bytes(b'first')
        with CleanupSession(max_files=1) as session:
            snapshot(self.file);expected=snapshot(other);other.write_bytes(b'second')
            with self.assertRaises(ValueError):delete_verified(other,expected)
            self.assertTrue(other.exists());self.assertEqual(len(session.files),1)

    def test_existing_read_handle_falls_back_and_does_not_weaken_deletion(self):
        with CleanupSession() as session:
            with self.file.open('rb') as reader:
                expected=snapshot(self.file);self.assertEqual(snapshot(self.file),expected)
                self.assertFalse(session.files);self.assertGreaterEqual(session.fallbacks,1)
            delete_verified(self.file,expected);self.assertFalse(self.file.exists())

    def test_hardlinked_input_is_preserved(self):
        link=self.root/'shared';os.link(self.file,link)
        with CleanupSession():
            expected=snapshot(self.file)
            with self.assertRaises(ValueError):delete_verified(self.file,expected)
        self.assertTrue(self.file.exists());self.assertTrue(link.exists())

    def test_link_added_during_pin_is_blocked_or_rejected_before_delete(self):
        link=self.root/'shared'
        with CleanupSession():
            expected=snapshot(self.file)
            try:os.link(self.file,link)
            except PermissionError:pass
            else:
                with self.assertRaises(ValueError):delete_verified(self.file,expected)
            self.assertTrue(self.file.exists())

    def test_handle_budget_is_bounded_and_nested_sessions_rejected(self):
        for value in (-1,257,True):
            with self.assertRaises(ValueError):CleanupSession(value)
        with CleanupSession():
            with self.assertRaises(RuntimeError):
                with CleanupSession():pass
