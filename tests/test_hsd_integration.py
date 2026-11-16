"""Offline checks using a real NOAA B13 object inventory (no network traffic)."""
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

import numpy as np

from ges.catalog import himawari_scene, utc_time
from ges.render import ir_to_rgba, make_global_area, render
from PIL import Image
from test_catalog import FakeS3


class HsdIntegrationTests(unittest.TestCase):
    def test_ir_gray_cold_clouds_white_warm_background_black(self):
        values=np.array([[173.15,213.15,273.15,318.15,np.nan]],dtype=np.float32)
        image=np.asarray(ir_to_rgba(values,'K','gray'))
        self.assertEqual(image[0,0,0],255)
        self.assertEqual(image[0,3,0],0)
        self.assertTrue((np.diff(image[0,:4,0].astype(int)) < 0).all())
        self.assertEqual(image[0,4,3],0)

    def test_real_b13_inventory(self):
        fixture = Path(__file__).parent / 'fixtures' / 'himawari8_20201029_1640_b13.json'
        objects = json.loads(fixture.read_text(encoding='utf-8-sig'))
        scene = himawari_scene(FakeS3(objects), utc_time('2020-10-29T16:40:00Z'), ('B13',), 10)
        self.assertEqual(scene.observed_utc, utc_time('2020-10-29T16:40:00Z'))
        self.assertEqual(scene.total_bytes, 24242460)
        self.assertEqual(len(scene.keys), 10)
        self.assertEqual(scene.object_sizes[0], 1236325)
        self.assertTrue(scene.keys[-1].endswith('_S1010.DAT.bz2'))

    def test_global_grid_orientation_and_dateline(self):
        area = make_global_area(512)
        lon, lat = area.get_lonlats()
        self.assertEqual(lon.shape, (256, 512))
        self.assertAlmostEqual(lon[0, 0], -180 + 360 / 1024)
        self.assertAlmostEqual(lon[0, -1], 180 - 360 / 1024)
        self.assertAlmostEqual(lat[0, 0], 90 - 180 / 512)
        self.assertAlmostEqual(lat[-1, 0], -90 + 180 / 512)

    def test_gray_missing_observations_do_not_cast_nan(self):
        values = np.array([[190., np.nan, np.inf, -np.inf, 99., 351.]], dtype=np.float32)
        with np.errstate(invalid='raise'):
            image = ir_to_rgba(values, 'K', 'gray')
        self.assertEqual(np.asarray(image)[0, :, 3].tolist(), [255, 0, 0, 0, 0, 0])

    def test_real_dateline_pixels_survive_global_resampling(self):
        from pyresample.geometry import AreaDefinition
        from satpy import Scene
        import xarray as xr
        import dask.array as da

        fixture = Path(__file__).parent / 'fixtures' / 'ahi_b13_dateline.npz'
        with np.load(fixture) as saved:
            values = saved['brightness_temperature']
            extent = tuple(saved['area_extent'])
        area = AreaDefinition('FLDK', 'Real AHI B13 subset', 'geosh8',
                              {'proj': 'geos', 'a': 6378137, 'rf': 298.257024882273,
                               'h': 35785863, 'lon_0': 140.7, 'units': 'm'},
                              128, 128, extent)
        scene = Scene()
        scene['B13'] = xr.DataArray(da.from_array(values), dims=('y', 'x'),
                                    attrs={'area': area, 'units': 'K', 'name': 'B13'})
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            manifest = folder / 'scene.json'
            manifest.write_text(json.dumps({
                'local_files': [str(fixture.resolve())], 'satellite': 'himawari8',
                'scene_id': 'real_b13_subset', 'observed_utc': '2020-10-29T16:40:00Z',
            }), encoding='utf-8')
            # Only HSD decoding is replaced: projection uses real calibrated pixels
            # and the actual Satpy/pyresample pipeline.
            with patch('ges.render.create_satpy_scene', return_value=scene):
                result = render(manifest, folder, 'ir-gray', 512)
            with Image.open(result) as image:
                self.assertEqual(image.getpixel((1, 128))[3], 255)  # 178.945 W
                self.assertEqual(image.getpixel((256, 128))[3], 0)  # 0.352 E


if __name__ == '__main__':
    unittest.main()
