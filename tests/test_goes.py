"""Offline reader/quality regressions from a real GOES-16 MCMIP crop."""
import json
from pathlib import Path
import unittest

import netCDF4
import numpy as np

from ges.catalog import goes_scene, utc_time
from ges.render import create_satpy_scene, mask_goes_ir_quality
from test_catalog import FakeS3

FIXTURES = Path(__file__).parent / 'fixtures'


class GoesTests(unittest.TestCase):
    def test_real_catalog_fractional_start_and_size(self):
        info = json.loads((FIXTURES / 'goes16_subset.json').read_text())
        scene = goes_scene(FakeS3([{'Key':info['original_key'], 'Size':430144438}]),
                           utc_time('2020-10-29T16:40:00Z'), 'goes16')
        self.assertEqual(scene.observed_utc, utc_time('2020-10-29T16:40:18.9Z'))
        self.assertEqual(scene.total_bytes, 430144438)

    def test_real_c13_mapping_and_per_band_quality(self):
        info = json.loads((FIXTURES / 'goes16_subset.json').read_text())
        path = FIXTURES / Path(info['original_key']).name
        scene = create_satpy_scene([str(path)], 'goes16')
        scene.load(['C13'])
        data = scene['C13']
        self.assertEqual(data.attrs['units'], 'K')
        self.assertEqual(data.attrs['calibration'], 'brightness_temperature')
        self.assertEqual(data.attrs['start_time'].microsecond, 900000)
        self.assertAlmostEqual(data.attrs['wavelength'].central, 10.35)
        with netCDF4.Dataset(path) as file:
            expected = file['CMI_C13'][:]
            flags = np.ma.filled(file['DQF_C13'][:], 255)
        np.testing.assert_allclose(data.compute().values, np.ma.filled(expected,np.nan), atol=1e-4)
        policy = mask_goes_ir_quality(scene, [str(path)], 'C13')
        self.assertIn('good_pixel_qf only', policy)
        masked = scene['C13'].compute().values
        self.assertTrue(np.isnan(masked[flags != 0]).all())
        self.assertEqual(int(np.isfinite(masked).sum()), 8244)
        np.testing.assert_allclose(masked[flags == 0], expected[flags == 0], atol=1e-4)


if __name__ == '__main__':
    unittest.main()
