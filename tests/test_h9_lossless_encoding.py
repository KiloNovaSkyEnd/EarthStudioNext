from pathlib import Path
import tempfile
import unittest
import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from rasterio.transform import from_origin
from ges_next.h9_lossless_encoding import encode_exact


class LosslessEncodingTests(unittest.TestCase):
    def test_rgba_alpha_geography_and_tags_survive_faster_lossless_level(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.tif'
            pixels=np.random.default_rng(99).integers(0,256,(4,517,519),dtype=np.uint8)
            pixels[3,:100]=0
            with rasterio.open(source,'w',driver='GTiff',height=517,width=519,count=4,
                    dtype='uint8',crs='EPSG:3857',transform=from_origin(12345,98765,500,500),
                    tiled=True,blockxsize=256,blockysize=256,compress='DEFLATE',zlevel=6) as dst:
                dst.write(pixels);dst.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha)
                dst.update_tags(observation_utc='2026-10-20T19:40:00Z');dst.update_tags(4,meaning='observed support')
            for level in [1,6]:
                result=encode_exact(source,root/f'level{level}.tif',level)
                self.assertTrue(result['all_rgba_grid_mask_and_metadata_exact'])
            original=source.read_bytes()
            with self.assertRaises(FileExistsError):encode_exact(source,source,1)
            self.assertEqual(source.read_bytes(),original)
