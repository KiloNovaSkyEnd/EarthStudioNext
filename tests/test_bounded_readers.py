"""Original HSD count bytes/chunks with lazy, repeatable Dask task identity."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import numpy as np
from ges.earth_validation.bounded_readers import BoundedAHIHSDFileHandler
from satpy.readers.ahi_hsd import AHIHSDFileHandler


class BoundedReaderTests(unittest.TestCase):
    def test_counts_offset_dtype_chunks_and_identity_match_stock(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'segment.DAT'
            values=np.arange(32*48,dtype='<u2').reshape(32,48)
            with path.open('wb') as stream:
                stream.write(b'original header'); values.tofile(stream)
            info=np.array([(32,48)],dtype=[('number_of_lines','u2'),('number_of_columns','u2')])
            header={'block2':info}; reader=SimpleNamespace(filename=str(path))
            def load(cls):
                with path.open('rb') as stream:
                    stream.seek(len(b'original header'))
                    return cls._read_data(reader,stream,header,500)
            stock=load(AHIHSDFileHandler); bounded=load(BoundedAHIHSDFileHandler)
            self.assertEqual(stock.dtype,bounded.dtype)
            self.assertEqual(stock.chunks,bounded.chunks)
            np.testing.assert_array_equal(stock.compute(),bounded.compute())
            self.assertEqual(bounded.name,load(BoundedAHIHSDFileHandler).name)
            del stock,bounded
            import gc
            gc.collect()
