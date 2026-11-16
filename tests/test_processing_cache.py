"""Lossless static input reuse and restart integrity, with tiny offline fixtures."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from pyresample import create_area_def
from PIL import Image
from ges.earth_validation.night_background import read_on_area
from ges.earth_validation.sequence_resume import verify
from ges.earth_validation.night_navigation import sample


class ProcessingCacheTests(unittest.TestCase):
    def test_direct_navigation_matches_gdal_nearest_on_real_geographic_grid(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'night.tif'
            rows,cols=np.indices((256,256))
            pixels=np.stack((rows,cols,(rows+cols)%256)).astype(np.uint8)
            with rasterio.open(source,'w',driver='GTiff',width=256,height=256,count=3,dtype='uint8',
                               crs='EPSG:4326',transform=from_bounds(-1,-1,1,1,256,256)) as out: out.write(pixels)
            area=create_area_def('sensor',{'proj':'geos','lon_0':0,'h':35785863,'a':6378137,'b':6356752.3},
                                 shape=(64,64),area_extent=(-20000,-20000,20000,20000),units='m')
            expected=read_on_area(source,area)
            with rasterio.open(source) as src: actual=sample(src,area)
            np.testing.assert_array_equal(actual,expected)

    def test_static_night_cache_is_exact_and_detects_corruption(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); source=root/'night.tif'
            pixels=np.arange(48,dtype=np.uint8).reshape(3,4,4)
            with rasterio.open(source,'w',driver='GTiff',width=4,height=4,count=3,dtype='uint8',
                               crs='EPSG:4326',transform=from_bounds(0,0,4,4,4,4)) as out: out.write(pixels)
            area=create_area_def('test','EPSG:4326',shape=(6,6),area_extent=(-1,-1,5,5))
            original=read_on_area(source,area)
            first=read_on_area(source,area,root/'cache')
            with patch('ges.earth_validation.night_background.WarpedVRT',side_effect=AssertionError('Repeated warp')):
                second=read_on_area(source,area,root/'cache')
            np.testing.assert_array_equal(original,first)
            np.testing.assert_array_equal(original,second)
            first._mmap.close()
            second._mmap.close()
            cache=next((root/'cache').glob('*.npy'))
            cache.write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError,'checksum'): read_on_area(source,area,root/'cache')

    def test_complete_sequence_receipt_reuses_pixels_and_rejects_edits(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); (root/'reports').mkdir(); (root/'processed').mkdir()
            image=root/'processed/frame.png'; Image.new('RGBA',(4096,2048)).save(image)
            metadata=root/'processed/metadata.json'
            metadata.write_text(json.dumps({'profile':'satpy-stock-geocolor-soft-rim-v1','night_navigation_version':2}))
            times=[str(number) for number in range(73)]
            (root/'inventory.json').write_text(json.dumps({'frames':times}))
            frames=[{'nominal_utc':utc,'file':str(image),'sources':[str(metadata)]} for utc in times]
            (root/'reports/stock_sequence.json').write_text(json.dumps({'complete_sequence':True,'frames':frames}))
            self.assertTrue(verify(root))
            with patch('ges.earth_validation.sequence_resume.Image.open',side_effect=AssertionError('Repeated decode')):
                self.assertTrue(verify(root))
            image.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'): verify(root)


if __name__=='__main__': unittest.main()
