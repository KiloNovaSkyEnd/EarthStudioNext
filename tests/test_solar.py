from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from ges.catalog import utc_time
from ges.render import make_global_area
from ges.solar import solar_weights, sun_direction, global_solar_weights, export_solar_weights


class SolarTests(unittest.TestCase):
    def test_documented_astronomy_reference(self):
        # Published Pyorbital example: zenith=62.685986438071602 degrees.
        w = solar_weights(utc_time('2012-05-15T15:45:00Z'), 12, 56)
        self.assertAlmostEqual(float(w.elevation_deg), 90 - 62.685986438071602, places=4)

    def test_timezones_represent_same_instant_and_naive_rejected(self):
        utc = utc_time('2020-10-29T16:40:00Z')
        local = utc.astimezone(timezone(timedelta(hours=8)))
        np.testing.assert_allclose(sun_direction(utc), sun_direction(local), atol=1e-12)
        with self.assertRaises(ValueError):
            solar_weights(datetime(2020, 10, 29, 16, 40), 140, 0)

    def test_equinox_noon_midnight_and_vector(self):
        when = utc_time('2020-03-20T12:00:00Z')
        sun = sun_direction(when)
        self.assertAlmostEqual(float(np.linalg.norm(sun)), 1, places=12)
        self.assertGreater(sun[0], .99)
        w = solar_weights(when, [0, 180], [0, 0])
        np.testing.assert_array_equal(w.day_cloud, [1, 0])
        np.testing.assert_array_equal(w.night_ir, [0, 1])
        np.testing.assert_array_equal(w.city_lights, [0, 1])
        self.assertGreater(w.surface_direct[0], .99)
        self.assertEqual(w.surface_direct[1], 0)

    def test_solstice_polar_day_and_night(self):
        for stamp, expected in [('2020-06-21T12:00:00Z', [1, 0]),
                                ('2020-12-21T12:00:00Z', [0, 1])]:
            w = solar_weights(utc_time(stamp), [0, 0], [90, -90])
            np.testing.assert_array_equal(w.day_cloud, expected)

    def test_sunrise_sunset_smooth_and_no_night_vis(self):
        for hour, rising in [(5, True), (17, False)]:
            start = utc_time(f'2020-03-20T{hour:02d}:30:00Z')
            sequence = [solar_weights(start + timedelta(minutes=i), 0, 0)
                        for i in range(91)]
            day = np.array([float(w.day_cloud) for w in sequence])
            delta = np.diff(day)
            self.assertTrue((delta >= -1e-6).all() if rising else (delta <= 1e-6).all())
            np.testing.assert_allclose(day[[0, -1]], [0, 1] if rising else [1, 0])
            self.assertLess(float(np.max(np.abs(delta))), .07)
            self.assertTrue(((day > 0) & (day < 1)).any())
            for w in sequence:
                if w.elevation_deg <= 0:
                    self.assertEqual(w.day_cloud, 0)
                    self.assertEqual(w.night_ir, 1)
                self.assertAlmostEqual(float(w.day_cloud + w.night_ir), 1, places=6)

    def test_date_line_and_midnight_are_continuous(self):
        before = utc_time('2020-12-31T23:59:59Z')
        after = utc_time('2021-01-01T00:00:01Z')
        np.testing.assert_allclose(sun_direction(before), sun_direction(after), atol=.0002)
        a = solar_weights(before, [-180, 180, 90], [0, 0, 0])
        self.assertEqual(a.day_cloud[0], a.day_cloud[1])
        b = solar_weights(after, [-180, 180, 90], [0, 0, 0])
        np.testing.assert_allclose(a.day_cloud, b.day_cloud, atol=.003)

    def test_cloud_and_city_weights_are_separate_from_surface(self):
        when = utc_time('2020-03-20T12:00:00Z')
        # Determine geometric sunrise meridian, then sample either side of it.
        sun = sun_direction(when)
        subsolar_lon = np.rad2deg(np.arctan2(sun[1], sun[0]))
        w = solar_weights(when, subsolar_lon + np.array([-93, -87]), 0)
        self.assertEqual(w.surface_direct[0], 0)
        self.assertEqual(w.night_ir[0], 1)
        self.assertAlmostEqual(float(w.city_lights[0]), .5, places=4)
        self.assertAlmostEqual(float(w.day_cloud[1]), .5, places=4)
        self.assertLess(w.surface_direct[1], .06)
        self.assertEqual(w.city_lights[1], 0)

    def test_global_grid_matches_imagery_pixel_centers(self):
        when = utc_time('2020-10-29T16:40:00Z')
        lon, lat = make_global_area(512).get_lonlats()
        expected = solar_weights(when, lon, lat)
        actual = global_solar_weights(when, 512)
        for name in vars(actual):
            np.testing.assert_allclose(getattr(actual, name), getattr(expected, name), atol=1e-5)

    def test_invalid_coordinates_and_display_ranges(self):
        when = utc_time('2020-10-29T16:40:00Z')
        for lon, lat in [(181, 0), (0, 91), (np.nan, 0), (0, np.inf)]:
            with self.assertRaises(ValueError):
                solar_weights(when, lon, lat)
        for kwargs in [{'day_full_elevation': 0}, {'lights_full_elevation': 0},
                       {'day_full_elevation': np.nan}]:
            with self.assertRaises(ValueError):
                solar_weights(when, 0, 0, **kwargs)
        for width in [511, 513, 8194, 512.0]:
            with self.assertRaises(ValueError):
                global_solar_weights(when, width)

    def test_export_labels_model_and_preserves_weights(self):
        when = utc_time('2020-10-29T16:40:00Z')
        with tempfile.TemporaryDirectory() as folder:
            target = export_solar_weights(when, Path(folder), 512)
            meta = json.loads(target.with_suffix('.json').read_text())
            self.assertIn('NOT observed', meta['kind'])
            self.assertEqual(meta['model_utc'], '2020-10-29T16:40:00Z')
            with np.load(target) as weights:
                self.assertEqual(weights['day_cloud'].shape, (256, 512))
                np.testing.assert_allclose(weights['day_cloud'] + weights['night_ir'], 1)
                with Image.open(target.parent / meta['preview']) as im:
                    np.testing.assert_array_equal(np.asarray(im), np.rint(weights['day_cloud'] * 255))


if __name__ == '__main__':
    unittest.main()
