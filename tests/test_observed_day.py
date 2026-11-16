import importlib.util
import unittest

import numpy as np

from ges.catalog import utc_time
from ges.goni_film import NativeCloudRenderer
from ges.observed_day import ObservedDayRenderer, observed_texture
from ges.solar import sun_direction


class ObservedTextureTests(unittest.TestCase):
    def test_missing_samples_remain_unsupported_and_inputs_untouched(self):
        rgb = np.full((2, 3, 3), .5, np.float32)
        rgb[0, 0] = np.nan
        support = np.ones((2, 3), bool)
        support[0, 1] = False
        original = rgb.copy()
        rgb.flags.writeable = False
        support.flags.writeable = False
        result = observed_texture(rgb, support)
        np.testing.assert_array_equal(rgb, original)
        self.assertTrue(np.isfinite(result).all())
        self.assertEqual(result[0, 0, 3], 0)
        self.assertEqual(result[0, 1, 3], 0)
        self.assertTrue((result[0, :2, :3] == 0).all())
        self.assertAlmostEqual(float(result[1, 1, 0]), .214041, places=5)

    def test_wrong_physical_input_types_are_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            observed_texture(np.ones((2, 3, 3), np.uint8)*128, np.ones((2, 3), bool))
        with self.assertRaises(ValueError):
            observed_texture(np.ones((2, 3, 3), np.float32), np.ones((2, 3), np.float32))


@unittest.skipUnless(importlib.util.find_spec('moderngl'), 'Optional GPU unavailable')
class ObservedDayGPUTests(unittest.TestCase):
    def setup_scene(self, night=False):
        stamp = '2022-08-31T04:00:00Z'
        sun = sun_direction(utc_time(stamp))
        forward = -sun if night else sun
        cam = dict(position=forward*7471, target=forward*6371, up=np.array([0., 0., 1.]), fov=3.)
        projection = dict(proj='geos', a=6378137., b=6356752.3, h=35785863., lon_0=140.7, sweep='y')
        meta = dict(projection=projection, extent_m=[-5500000., -5500000., 5500000., 5500000.], nominal_utc=stamp)
        obs = dict(projection=projection, area_extent_m=meta['extent_m'], nominal_utc=stamp, output_shape_yx=[64, 64])
        lights = np.full((16, 32, 3), 40, np.uint8)
        r = ObservedDayRenderer(lights, 48, 48, 1)
        cloud = np.full((64, 64, 4), [180, 180, 180, 230], np.uint8)
        height = np.full((32, 32), 10, np.float32)
        r.update(cloud, height, meta)
        rgb = np.full((64, 64, 3), [.1, .25, .4], np.float32)
        r.set_observation(rgb, np.ones((64, 64), bool), obs)
        return r, cam, sun, meta, obs, cloud, height, lights

    def test_day_uses_actual_rgb_once_independent_of_modeled_cloud_and_path(self):
        r, cam, sun, *_ = self.setup_scene()
        try:
            a = r.render(cam, sun)
            b = r.render(cam, sun, clouds=False, atmosphere=False, airglow=False)
            np.testing.assert_array_equal(a, b)
            np.testing.assert_allclose(a[24, 24], [26, 64, 102], atol=1)
        finally:
            r.close()

    def test_missing_data_is_marked_and_new_frame_cannot_reuse_old_rgb(self):
        r, cam, sun, meta, obs, cloud, height, _ = self.setup_scene()
        try:
            rgb = np.full((64, 64, 3), np.nan, np.float32)
            r.set_observation(rgb, np.ones((64, 64), bool), obs)
            a = r.render(cam, sun, clouds=False, atmosphere=False, airglow=False)
            self.assertGreater(np.unique(a.reshape(-1, 3), axis=0).shape[0], 1)
            r.update(cloud, height, meta)
            with self.assertRaises(ValueError):
                r.render(cam, sun)
            wrong = dict(obs, nominal_utc='2022-08-31T05:00:00Z')
            with self.assertRaises(ValueError):
                r.set_observation(rgb, np.ones((64, 64), bool), wrong)
        finally:
            r.close()

    def test_night_preserves_native_lights_clouds_and_airglow_without_day_rgb(self):
        r, cam, sun, meta, obs, cloud, height, lights = self.setup_scene(night=True)
        q = NativeCloudRenderer(np.zeros((2, 4, 3), np.uint8), lights, 48, 48, 1)
        try:
            q.update(cloud, height, meta)
            np.testing.assert_array_equal(q.render(cam, sun), r.render(cam, sun))
            with self.assertRaises(ValueError):
                r.render(cam, -sun)
        finally:
            r.close()
            q.close()


if __name__ == '__main__':
    unittest.main()
