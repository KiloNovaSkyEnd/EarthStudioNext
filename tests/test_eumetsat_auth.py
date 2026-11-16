import os
from pathlib import Path
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from ges.eumetsat_auth import save_credentials,load_credentials


@unittest.skipUnless(os.name=='nt','Windows DPAPI only')
class EumetsatAuthTests(unittest.TestCase):
    def test_noninteractive_setup_never_prompts_or_authenticates(self):
        import configure_eumetsat
        with redirect_stdout(io.StringIO()), patch('sys.stdin.isatty',return_value=False), \
                patch('configure_eumetsat.getpass.getpass') as prompt, \
                patch('configure_eumetsat.authenticated_token') as authenticate:
            self.assertEqual(configure_eumetsat.main(),1)
            prompt.assert_not_called()
            authenticate.assert_not_called()

    def test_encrypted_roundtrip_never_stores_plaintext(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'credentials.dpapi'
            save_credentials('dummy-test-consumer-key','dummy-test-consumer-secret',path)
            encrypted=path.read_bytes()
            self.assertNotIn(b'dummy-test-consumer-key',encrypted)
            self.assertNotIn(b'dummy-test-consumer-secret',encrypted)
            self.assertEqual(load_credentials(path),('dummy-test-consumer-key','dummy-test-consumer-secret'))
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_corrupt_or_missing_credentials_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'credentials.dpapi'
            with self.assertRaises(FileNotFoundError): load_credentials(path)
            path.write_bytes(b'invalid-ciphertext')
            with self.assertRaises(RuntimeError): load_credentials(path)

    def test_empty_values_do_not_replace_existing_store(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'credentials.dpapi'
            save_credentials('dummy-key','dummy-secret',path)
            before=path.read_bytes()
            with self.assertRaises(ValueError): save_credentials('', 'secret',path)
            self.assertEqual(path.read_bytes(),before)


if __name__=='__main__': unittest.main()
