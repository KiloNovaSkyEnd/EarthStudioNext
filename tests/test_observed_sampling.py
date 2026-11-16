import unittest

import dask.array as da
import numpy as np
import xarray as xr
from pyresample.geometry import AreaDefinition
from satpy import Scene

from ges.observed_rgb import _native_crop, RECIPE, PROFILE


class NativeObservedSamplingTests(unittest.TestCase):
    def fixture(self):
        target = AreaDefinition('target', 'target', 'geos',
            dict(proj='geos', lon_0=140.7, h=35785863, a=6378137, b=6356752.3),
            4, 4, [-2000, -2000, 2000, 2000])
        scene = Scene()
        for name in ['B01', 'B02', 'B03', 'B04']:
            n = 12 if name == 'B03' else 6
            area = AreaDefinition(name, name, 'geos', target.proj_dict, n, n, [-3000,-3000,3000,3000])
            values = np.ones((n,n), np.float32)*8
            scene[name] = xr.DataArray(da.from_array(values,chunks=(n,n)),dims=['y','x'],
                                      attrs=dict(name=name, area=area, units='%'))
        return scene,target

    def test_true_red_footprint_mean_cancels_subpixel_checker_not_decimation(self):
        scene,target = self.fixture()
        red = scene['B03']
        values = np.indices(red.shape).sum(0)%2*4+6
        red.data = da.from_array(values.astype('float32'), chunks=(12,12))
        cropped,support = _native_crop(scene,target)
        actual = cropped.resample(target,resampler='native')['B03'].compute().values
        np.testing.assert_array_equal(actual,np.full((4,4),8))
        self.assertTrue(support.compute().all())
        self.assertEqual(scene['B03'].shape,(12,12))

    def test_one_missing_contributor_invalidates_only_its_footprint(self):
        scene,target = self.fixture()
        values = np.full((12,12),8.,np.float32)
        values[4,4] = np.nan
        scene['B03'].data = da.from_array(values,chunks=(12,12))
        cropped,support = _native_crop(scene,target)
        expected = np.ones((4,4),bool)
        expected[1,1] = False
        np.testing.assert_array_equal(support.compute(),expected)
        # Satpy alone would average the three remaining samples and hide the hole.
        rawmean = cropped.resample(target,resampler='native')['B03'].compute().values
        self.assertEqual(rawmean[1,1],8.)

    def test_crop_matches_larger_footprint_including_cloud_step(self):
        scene,target = self.fixture()
        values = np.ones((12,12),np.float32)*4
        values[:,6:] = 40
        scene['B03'].data = da.from_array(values,chunks=(12,12))
        cropped,_ = _native_crop(scene,target)
        actual = cropped.resample(target,resampler='native')['B03'].compute().values
        whole = values.reshape(6,2,6,2).mean((1,3))[1:5,1:5]
        np.testing.assert_array_equal(actual,whole)
        np.testing.assert_array_equal(actual[0],[4,4,40,40])

    def test_fractional_or_upsampled_target_rejected(self):
        scene,target = self.fixture()
        for n,extent in [(4,[-1900,-2000,2100,2000]),(8,target.area_extent)]:
            bad = AreaDefinition('bad','bad','geos',target.proj_dict,n,n,extent)
            with self.assertRaisesRegex(ValueError,'integer aligned'):
                _native_crop(scene,bad)

    def test_subdecimetre_navigation_rounding_allowed_but_not_whole_pixel_shift(self):
        scene,target = self.fixture()
        rounded = AreaDefinition('rounded','rounded','geos',target.proj_dict,4,4,
                                 [-1999.92,-2000,2000.08,2000])
        cropped,support = _native_crop(scene,rounded)
        np.testing.assert_array_equal(support.compute(),np.ones((4,4),bool))
        self.assertEqual(cropped['B03'].shape,(8,8))

    def test_profile_invalidates_old_cache_and_avoids_ratio_sharpen(self):
        self.assertTrue(PROFILE.endswith('v2'))
        self.assertIn('core.GenericCompositor',RECIPE)
        self.assertNotIn('SelfSharpenedRGB',RECIPE)
        self.assertNotIn('sunz_reduced',RECIPE)


if __name__ == '__main__':
    unittest.main()
