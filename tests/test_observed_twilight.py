import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np

from ges.atmosphere_scattering import geographic
from ges.observed_day import ObservedDayRenderer
from ges.observed_rgb import RECIPE
from ges.solar import solar_weights, sun_direction


def crossing(lon, lat, rising):
    start = datetime(2022, 8, 31, tzinfo=timezone.utc)
    previous = float(solar_weights(start, lon, lat).elevation_deg)-3
    for i in range(1, 97):
        right = start+timedelta(minutes=15*i)
        value = float(solar_weights(right, lon, lat).elevation_deg)-3
        if (previous < 0 <= value) if rising else (previous > 0 >= value):
            left = right-timedelta(minutes=15)
            for _ in range(28):
                mid = left+(right-left)/2
                above = float(solar_weights(mid, lon, lat).elevation_deg) >= 3
                if above == rising:
                    right = mid
                else:
                    left = mid
            return left+(right-left)/2
        previous = value
    raise AssertionError('No requested twilight crossing')


class RawTwilightCorrectionTests(unittest.TestCase):
    def test_configured_modifier_preserves_day_and_missing_but_avoids_excess_low_sun_subtraction(self):
        import dask.array as da
        import xarray as xr
        import yaml
        from satpy.modifiers.atmosphere import PSPRayleighReflectance
        from pyspectral.rayleigh import Rayleigh as ActualRayleigh
        recipe = yaml.load(RECIPE, Loader=yaml.UnsafeLoader)
        options = recipe['modifiers']['observed_rayleigh'].copy()
        options.pop('modifier')
        modifier = PSPRayleighReflectance(name='observed_rayleigh', **options)
        angles = np.array([[60., 70., 80., 85., 89., 90.]], np.float32)
        raw = np.full_like(angles, .3)
        raw[0, 2] = np.nan
        def field(values):
            return xr.DataArray(da.from_array(values, chunks=values.shape), dims=['y', 'x'],
                                attrs=dict(name='B01', platform_name='Himawari-8', sensor='ahi', wavelength=[.45, .47, .49], units='%'))
        with patch('pyspectral.rayleigh.Rayleigh') as factory:
            corrector = factory.return_value
            corrector.get_reflectance.return_value = da.full(angles.shape, .4, dtype=np.float32)
            # Use the real installed Pyspectral angle reduction, mock only LUT I/O.
            corrector.reduce_rayleigh_highzenith.side_effect = ActualRayleigh.reduce_rayleigh_highzenith
            result = modifier([field(raw), field(np.full_like(raw, .3))],
                              optional_datasets=[field(np.zeros_like(raw)), field(np.zeros_like(raw)),
                                                 field(np.zeros_like(raw)), field(angles)]).compute().values
        self.assertAlmostEqual(float(result[0, 0]), -.1, places=6)
        self.assertAlmostEqual(float(result[0, 1]), -.1, places=6)
        self.assertTrue(np.isnan(result[0, 2]))
        self.assertAlmostEqual(float(result[0, 3]), .2, places=6)
        self.assertAlmostEqual(float(result[0, 5]), .3, places=6)
        self.assertTrue(np.isnan(raw[0, 2]))


@unittest.skipUnless(importlib.util.find_spec('moderngl'), 'Optional GPU unavailable')
class RegionalTwilightGPUTests(unittest.TestCase):
    def test_same_angle_has_same_handoff_at_dawn_and_dusk_in_both_hemispheres(self):
        # Synthetic constant colour: geometry invariance only, NOT new weather.
        for lon, lat in [(115., 25.), (145., 40.), (130., -10.), (150., -35.), (170., 0.)]:
            projection = dict(proj='geos', a=6378137., b=6356752.3, h=35785863., lon_0=lon, sweep='y')
            extent = [-5500000., -5500000., 5500000., 5500000.]
            r = ObservedDayRenderer(np.zeros((16, 32, 3), np.uint8), 33, 33, 1)
            cam = dict(position=geographic(lon, lat, 7471), target=geographic(lon, lat, 6371), up=np.array([0., 0., 1.]), fov=1.)
            try:
                results = []
                for rising in [True, False]:
                    stamp = crossing(lon, lat, rising)
                    meta = dict(projection=projection, extent_m=extent, nominal_utc=stamp.isoformat())
                    obs = dict(projection=projection, area_extent_m=extent, nominal_utc=stamp.isoformat(),
                               output_shape_yx=[64, 64], source_fade_applied=False)
                    r.update(np.zeros((64, 64, 4), np.uint8), np.full((32, 32), np.nan, np.float32), meta)
                    rgb = np.full((64, 64, 3), .3, np.float32)
                    r.set_observation(rgb, np.ones((64, 64), bool), obs)
                    image = r.render(cam, sun_direction(stamp), weight_debug=True, float_output=True,
                                     clouds=False, atmosphere=False, airglow=False)
                    encoded = float(image[16, 16, 0])
                    weight = ((encoded+.055)/1.055)**2.4
                    t = np.sin(np.deg2rad(3))/np.sin(np.deg2rad(6))
                    expected = t*t*t*(6*t*t-15*t+10)
                    self.assertAlmostEqual(weight, expected, delta=.0002)
                    results.append(weight)
                    with self.assertRaises(ValueError):
                        r.set_observation(rgb, np.ones((64, 64), bool), {**obs, 'source_fade_applied': True})
                self.assertAlmostEqual(*results, delta=.0002)
            finally:
                r.close()


if __name__ == '__main__':
    unittest.main()
