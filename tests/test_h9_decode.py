from pathlib import Path
import bz2
import tempfile
import unittest
from ges_next.h9_decode import decode_originals

class H9DecodeTests(unittest.TestCase):
    def test_parallel_decode_preserves_exact_data_and_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);sources=[];expected=[]
            for i in range(4):
                data=bytes(range(256))*64+bytes([i]);expected.append(data)
                path=folder/f'HS_H09_test_{i}.DAT.bz2';path.write_bytes(bz2.compress(data));sources.append(path)
            before=[p.read_bytes() for p in sources]
            dest=folder/'decoded';dest.mkdir()
            actual=decode_originals(sources,dest,workers=4)
            self.assertEqual([p.read_bytes() for p in actual],expected)
            self.assertEqual([p.read_bytes() for p in sources],before)
            with self.assertRaises(FileExistsError):decode_originals(sources,dest)
    def test_corrupt_bzip2_cannot_be_accepted_as_hsd(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'bad.DAT.bz2';source.write_bytes(b'not a bzip2 stream')
            dest=folder/'decoded';dest.mkdir()
            with self.assertRaises(OSError):decode_originals([source],dest)
            self.assertEqual(source.read_bytes(),b'not a bzip2 stream')

if __name__=='__main__':unittest.main()
