import bz2,hashlib,json,os,tempfile,unittest
from pathlib import Path
from ges_next.performance.stream_decode import decode,locked_source
from ges_next.production.h9_source import decode as original
from unittest.mock import patch


class StreamDecodeTests(unittest.TestCase):
    def test_exact_receipts_multistream_trailing_and_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);paths=[]
            for i in range(3):
                p=root/f'{i}.DAT.bz2';p.write_bytes(bz2.compress(bytes(range(256))*100+i.to_bytes(1))+bz2.compress(b'second stream')+b'trailing');paths.append(p)
            with patch('ges_next.performance.policy.settings',return_value={'decode_workers':2}):a,ia=original(paths,root/'old')
            metrics=[];b,ib=decode(paths,root/'new',2,metrics)
            self.assertEqual(ia,ib)
            self.assertEqual([p.read_bytes() for p in a],[p.read_bytes() for p in b])
            self.assertTrue(all(json.loads(x.with_suffix('.decode.json').read_text())==json.loads(y.with_suffix('.decode.json').read_text()) for x,y in zip(a,b)))
            self.assertEqual(sum(m['compressed_read_bytes'] for m in metrics),sum(p.stat().st_size for p in paths))
            self.assertEqual(decode(paths,root/'new',2)[1],ia)
            b[0].write_bytes(b'corrupt')
            with self.assertRaises(ValueError):decode(paths,root/'new',2)

    def test_truncation_or_bad_stream_never_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i,data in enumerate((b'bad',bz2.compress(b'payload'*1000)[:-6])):
                p=root/f'{i}.DAT.bz2';p.write_bytes(data)
                with self.assertRaises((EOFError,OSError)):decode([p],root/'decoded',1)
                self.assertFalse((root/'decoded'/f'{i}.DAT').exists())
                self.assertFalse((root/'decoded'/f'{i}.decode.json').exists())

    @unittest.skipUnless(os.name=='nt','Windows production lock')
    def test_source_cannot_change_or_replace_during_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'input';p.write_bytes(b'original');replacement=root/'other';replacement.write_bytes(b'other')
            with locked_source(p):
                with self.assertRaises(OSError):p.write_bytes(b'changed')
                with self.assertRaises(OSError):replacement.replace(p)
            self.assertEqual(p.read_bytes(),b'original')

    def test_missing_receipt_and_changed_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'a.DAT.bz2';p.write_bytes(bz2.compress(b'original'))
            out=root/'decoded';decode([p],out,1);p.write_bytes(bz2.compress(b'changed'))
            with self.assertRaises(ValueError):decode([p],out,1)
            (out/'a.decode.json').unlink()
            with self.assertRaises(ValueError):decode([p],out,1)

    def test_bad_write_readback_cannot_install_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'a.DAT.bz2';p.write_bytes(bz2.compress(b'original'))
            with patch('ges_next.performance.stream_decode.digest',return_value='bad-readback'):
                with self.assertRaisesRegex(ValueError,'read-back'):decode([p],root/'decoded',1)
            self.assertFalse((root/'decoded/a.DAT').exists())
            self.assertFalse((root/'decoded/a.decode.json').exists())
