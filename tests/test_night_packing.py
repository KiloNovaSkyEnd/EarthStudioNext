"""All float32 bits and array window semantics survive tiled lossless storage."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import numpy as np
from ges.earth_validation.night_packing import packed


class NightPackingTests(unittest.TestCase):
    def test_rgb_values_nan_bits_and_windows_are_exact(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'grid.npy'
            values=np.random.default_rng(2).integers(0,256,(3,19,23)).astype(np.float32)
            values[:,4:7,8:13]=np.nan; np.save(path,values)
            source=np.load(path,mmap_mode='r'); reader=packed(source)
            np.testing.assert_array_equal(values.view(np.uint32),reader[...].view(np.uint32))
            for index in ((1,slice(2,17,2),slice(3,21,3)),(slice(None),slice(None,None,-1),slice(None)),
                          (2,8,9),(slice(None),slice(0,0),slice(None))):
                np.testing.assert_array_equal(np.asarray(values[index]).view(np.uint32),
                                              np.asarray(reader[index]).view(np.uint32))
            np.testing.assert_array_equal(packed(source)[:].view(np.uint32),values.view(np.uint32))
            import dask.array as da
            from ges.earth_validation.arrays import ReadOnlyArray
            lazy=da.from_array(ReadOnlyArray(reader),chunks=(3,7,9),asarray=False,fancy=False,
                name=False,meta=np.empty((0,0,0),np.float32))
            np.testing.assert_array_equal(lazy.compute().view(np.uint32),values.view(np.uint32))
            source._mmap.close()

    def test_fractional_values_are_never_quantized(self):
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'grid.npy'; values=np.zeros((3,8,8),np.float32)
            values[0,1,1]=.5; np.save(path,values)
            source=np.load(path,mmap_mode='r')
            with self.assertRaisesRegex(ValueError,'precision reduction'): packed(source)
            source._mmap.close()
