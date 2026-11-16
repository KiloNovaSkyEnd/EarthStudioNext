from pathlib import Path
import tempfile
import unittest
from ges.export import export_product

class ExportTests(unittest.TestCase):
    def test_keeps_both_exports_and_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            image=tmp/'cache'/'map.png'; image.parent.mkdir()
            image.write_bytes(b'fake png bytes')
            image.with_suffix('.json').write_text('{"utc":"2020-10-29T16:40Z"}')
            a=export_product(image,tmp/'export')
            b=export_product(image,tmp/'export')
            self.assertNotEqual(a,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertTrue(a.with_suffix('.json').is_file())
            self.assertTrue(b.with_suffix('.json').is_file())

if __name__=='__main__': unittest.main()
