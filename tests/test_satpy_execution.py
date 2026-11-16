"""Compare execution optimisation directly against the installed stock math."""
import unittest
import numpy as np
import dask.array as da
import xarray as xr
from satpy.composites.mask import LowCloudCompositor,HighCloudCompositor
from ges.earth_validation.satpy_execution import BoundedLowCloudCompositor,BoundedHighCloudCompositor


class SatpyExecutionTests(unittest.TestCase):
    def test_stock_high_cloud_values_and_metadata_including_latitude_thresholds(self):
        from pyresample.geometry import AreaDefinition
        area=AreaDefinition('test','','',{'proj':'geos','lon_0':0,'h':35785863,'a':6378137,
            'b':6356752.3,'sweep':'y'},64,48,(-5000000,-5000000,5000000,5000000))
        rng=np.random.default_rng(6)
        for dtype in (np.float32,np.float64):
            values=rng.uniform(180,320,(48,64)).astype(dtype); values[3,4]=np.nan
            data=xr.DataArray(da.from_array(values,chunks=(12,16)),dims=('y','x'),
                coords={'y':np.arange(48),'x':np.arange(64)},attrs={'area':area,'name':'IR'})
            stock=HighCloudCompositor('high')([data])
            bounded=BoundedHighCloudCompositor('high')([data])
            # Dask's generated DataArray name hashes its execution graph.
            # Product attrs (including the actual product name) stay identical.
            xr.testing.assert_identical(stock.rename(None).compute(),bounded.rename(None).compute())

    def test_stock_low_cloud_values_coordinates_and_attributes(self):
        rng = np.random.default_rng(26)
        arrays = [rng.uniform(-2, 8, (48, 64)).astype('float32'),
                  rng.choice([229., 230., 231., np.nan], (48, 64)).astype('float32'),
                  rng.choice([0., 100., 50., np.nan], (48, 64)).astype('float32')]
        arrays[0][3:8, 5:9] = np.nan
        inputs = [xr.DataArray(da.from_array(a, chunks=(12, 16)), dims=('y', 'x'),
                  coords={'y': np.arange(48), 'x': np.arange(64)},
                  attrs={'name': f'band{i}'}) for i, a in enumerate(arrays)]
        for options in ({}, {'values_land': 100, 'range_land': (-1, 3),
                            'range_water': (0, 4), 'transition_gamma': 1.7}):
            with self.subTest(options=options):
                stock = LowCloudCompositor('low', **options)(inputs)
                bounded = BoundedLowCloudCompositor('low', **options)(inputs)
                xr.testing.assert_identical(stock.compute(), bounded.compute())

    def test_bad_input_count(self):
        with self.assertRaisesRegex(ValueError, 'Expected 3'):
            BoundedLowCloudCompositor('low')([])
