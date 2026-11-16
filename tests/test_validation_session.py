import json,os,tempfile,unittest
from pathlib import Path
from PIL import Image
from ges_next.production.assets import digest,write_json
from ges_next.production.validation_session import ValidationSession,load_image_once


@unittest.skipUnless(os.name=='nt','Windows protected-handle cache')
class ValidationSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd()/'reports');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.file=self.root/'image.png'
        Image.new('RGB',(8,8),(20,30,40)).save(self.file)

    def test_reuse_only_while_mutation_and_replacement_are_blocked(self):
        expected=digest(self.file)
        with ValidationSession() as session:
            self.assertEqual(digest(self.file),expected);self.assertEqual(digest(self.file),expected)
            self.assertEqual(session.hash_reads,1)
            with self.assertRaises(PermissionError):self.file.write_bytes(b'changed')
            other=self.root/'candidate';other.write_bytes(b'replaced')
            with self.assertRaises(PermissionError):other.replace(self.file)
            with Image.open(self.file) as image:load_image_once(self.file,image)
            with Image.open(self.file) as image:load_image_once(self.file,image)
            self.assertEqual(len(session.decoded),1)
        self.file.write_bytes(b'changed');self.assertNotEqual(digest(self.file),expected)

    def test_exception_releases_handles_and_no_stale_cross_session_cache(self):
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with ValidationSession():digest(self.file);raise RuntimeError('fixture')
        self.file.write_bytes(b'new content')
        with ValidationSession() as session:
            self.assertEqual(digest(self.file),digest(self.file));self.assertEqual(session.hash_reads,1)

    def test_corrupt_image_is_not_marked_as_decoded(self):
        self.file.write_bytes(b'not an image')
        with ValidationSession() as session:
            digest(self.file)
            with self.assertRaises(OSError):
                with Image.open(self.file) as image:load_image_once(self.file,image)
            self.assertEqual(session.decoded,set())
