import unittest
import uuid
from pathlib import Path
import dask
import dask.array as da
import numpy as np
from ges.earth_validation.spill import ArraySpillCache
from ges_next.production.store_target import StoreTarget


class SpillTests(unittest.TestCase):
    def test_mutable_output_survives_forced_spill(self):
        root=Path('reports/production_spill_fixtures')/uuid.uuid4().hex
        root.mkdir(parents=True)
        arrays=[np.lib.format.open_memmap(root/f'{i}.npy',mode='w+',dtype='uint16',shape=(128,128)) for i in range(3)]
        sources=[da.full((128,128),i+1,chunks=(32,32),dtype='uint16') for i in range(3)]
        stores=da.store(sources,[StoreTarget(a) for a in arrays],compute=False,lock=False)
        spill=root/'spill';spill.mkdir()
        cache=ArraySpillCache(spill,limit=1024)
        dask.compute(stores,scheduler='threads',num_workers=2,cache=cache)
        for i,array in enumerate(arrays): np.testing.assert_array_equal(array,i+1)


if __name__=='__main__': unittest.main()
