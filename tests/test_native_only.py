"""Guards for global native coverage, no proxy inputs, and bounded lazy background."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import numpy as np
import dask.array as da
import rasterio
from rasterio.transform import from_bounds
from PIL import Image
from pyproj import CRS
from ges.earth_validation.fusion import fuse
from ges.earth_validation.native_cells import cells,SIZE,write
from ges.earth_validation.camera_tiles import cell_bounds
from ges.earth_validation.stock import ReadOnlyArray


class NativeOnlyTests(unittest.TestCase):
    @patch('ges.earth_validation.native_cells.check_disk')
    @patch('ges.earth_validation.native_cells.fuse',side_effect=lambda inputs,lon,lat,**kw:fuse(inputs,lon,lat))
    def test_three_band_native_source_has_windowed_valid_alpha(self,_fusion,_disk):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/'geo_color.tif'
            crs=CRS.from_dict({'proj':'geos','lon_0':2.5,'h':35785863,'a':6378137,'b':6356752.3,'sweep':'y'})
            pixels=np.zeros((3,64,64),np.uint8); pixels[:]=np.array([17,28,39])[:,None,None]
            with rasterio.open(source,'w',driver='GTiff',width=64,height=64,count=3,dtype='uint8',
                               crs=crs,transform=from_bounds(-1000000,-1000000,1000000,1000000,64,64)) as out: out.write(pixels)
            metadata=root/'metadata.json'
            metadata.write_text(json.dumps({'native_grid_tile':True,'night_navigation_version':2,
                'shape':[64,64],'crs_wkt':crs.to_wkt(),'extent':[-1000000,-1000000,1000000,1000000]}))
            result=write(root,[metadata],36,18,1,'2022-09-01T05:00:00Z')
            self.assertEqual(result['valid_fraction'],1)
            with Image.open(result['texture']) as image:
                actual=np.asarray(image)
                np.testing.assert_array_equal(actual[SIZE//2,SIZE//2],[17,28,39,255])

    def test_complete_nonpolar_grid_and_no_coarse_levels(self):
        grid=cells()
        self.assertEqual(len(grid),2016); self.assertEqual(len(set(grid)),2016)
        self.assertEqual(cell_bounds(*grid[0]),(-180,-70,-175,-65))
        self.assertEqual(cell_bounds(*grid[-1]),(175,65,180,70))
        self.assertLess(111700*5/SIZE,500)

    def test_proxy_sources_cannot_enter_final_globe(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); metadata=root/'coarse.json'
            metadata.write_text(json.dumps({'native_grid_tile':False,'night_navigation_version':2}))
            with self.assertRaisesRegex(ValueError,'refuses coarse'):
                write(root,[metadata],61,22,1,'2022-09-01T05:00:00Z')
            self.assertFalse((root/'processed').exists())

    def test_lazy_static_grid_preserves_values_without_eager_copy(self):
        class NoCopy(np.ndarray):
            def copy(self,*args,**kwargs): raise AssertionError('Whole-array copy')
        values=np.arange(3*16*16,dtype=np.float32).reshape(3,16,16).view(NoCopy)
        lazy=da.from_array(ReadOnlyArray(values),chunks=(3,4,4),asarray=False,
                           fancy=False,name=False,meta=np.empty((0,0,0),np.float32))
        np.testing.assert_array_equal(lazy.compute(),values)


if __name__=='__main__': unittest.main()
