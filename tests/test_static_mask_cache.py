"""Stock nearest output is unchanged and is reused without new interpolation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import numpy as np
import dask.array as da
import xarray as xr
from pyresample.geometry import AreaDefinition
from satpy import Scene
from ges.earth_validation.static_mask_cache import cached


class StaticMaskCacheTests(unittest.TestCase):
    @patch('ges.earth_validation.static_mask_cache.check_disk')
    def test_exact_values_missing_mask_navigation_and_reuse(self,_disk):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); (root/'scratch').mkdir()
            reference=root/'reference'; reference.write_bytes(b'immutable-fixture')
            source=AreaDefinition('source','','','EPSG:4326',80,80,(-2,-2,2,2))
            target=AreaDefinition('target','','',{'proj':'geos','lon_0':0,'h':35785863,
                'a':6378137,'b':6356752.3,'sweep':'y'},32,32,(-100000,-100000,100000,100000))
            values=np.zeros((80,80),np.float32); values[:,40:]=100; values[35:38,35:38]=np.nan
            data=xr.DataArray(da.from_array(values,chunks=(16,16)),dims=('y','x'),
                attrs={'name':'mask','standard_name':'land_water_mask','area':source})
            scene=Scene(); scene['mask']=data
            expected=scene.resample(target,datasets=['mask'],generate=False,
                resampler='nearest',radius_of_influence=6000)['mask']
            folder=root/'processed/static_landmask_grids_v1'
            first=cached(data,target,reference,folder)
            xr.testing.assert_identical(expected.rename(None).compute(),first.rename(None).compute())
            with patch.object(Scene,'resample',side_effect=AssertionError('Cache hit must not resample')):
                second=cached(data,target,reference,folder)
                np.testing.assert_array_equal(first.compute(),second.compute())
                regrouped=cached(data,target,reference,folder,compute_chunk=1024)
                np.testing.assert_array_equal(first.compute(),regrouped.compute())
                del regrouped
            del first,second,expected,scene
            import gc; gc.collect()

    def test_weather_data_cannot_enter_static_cache(self):
        with self.assertRaisesRegex(ValueError,'Only static'):
            cached(xr.DataArray([1],attrs={'standard_name':'brightness_temperature'}),None,None,None)
