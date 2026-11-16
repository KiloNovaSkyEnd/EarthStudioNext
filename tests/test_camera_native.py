"""Offline checks guarding original bytes and geographic cell navigation."""
import bz2
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import numpy as np
from pyresample import create_area_def
from ges.earth_validation.hsd_cache import expand
from ges.earth_validation.camera_tiles import cell_bounds,sensor_crop,coarse_disk_factor


class CameraNativeTests(unittest.TestCase):
    def test_nominal_goes_grid_does_not_misclassify_501_m_as_one_km_lod(self):
        from types import SimpleNamespace
        goes=SimpleNamespace(width=21696,height=21696,pixel_size_x=501.004322)
        self.assertEqual(coarse_disk_factor(goes,500),4)
        self.assertEqual(goes.width//coarse_disk_factor(goes,500),5424)
        seviri=SimpleNamespace(width=3712,height=3712,pixel_size_x=3000)
        self.assertEqual(coarse_disk_factor(seviri,3000),1)

    @patch('ges.earth_validation.hsd_cache.check_disk')
    def test_decompression_is_exact_and_changed_cache_is_rejected(self,_disk):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/'observation.DAT.bz2'
            payload=bytes(range(256))*4096; source.write_bytes(bz2.compress(payload))
            raw=source.read_bytes()
            output=expand([source],root,'test')[0]
            self.assertEqual(output.read_bytes(),payload)
            stamp=output.stat().st_mtime_ns
            self.assertEqual(expand([source],root,'test')[0].stat().st_mtime_ns,stamp)
            self.assertEqual(source.read_bytes(),raw)
            output.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'cache changed'): expand([source],root,'test')

    def test_cells_meet_at_dateline_and_polar_partial_row(self):
        self.assertEqual(cell_bounds(0,18),(-180,0,-175,5))
        self.assertEqual(cell_bounds(71,18),(175,0,180,5))
        self.assertEqual(cell_bounds(8,4,3),(140,70,180,90))
        with self.assertRaises(ValueError): cell_bounds(72,0)

    def test_native_crop_retains_original_grid_spacing_and_contains_target(self):
        area=create_area_def('fixture',{'proj':'geos','lon_0':140.7,'h':35785863,
            'a':6378137,'b':6356752.31414,'sweep':'y'},shape=(22000,22000),
            area_extent=(-5500000,-5500000,5500000,5500000),units='m')
        crop=sensor_crop(area,(125,20,130,25))
        self.assertEqual(crop.pixel_size_x,500)
        self.assertEqual(crop.width%4,0); self.assertEqual(crop.height%4,0)
        self.assertGreater(crop.width,900)
        self.assertIsNone(sensor_crop(area,(-50,20,-45,25)))


if __name__=='__main__': unittest.main()
