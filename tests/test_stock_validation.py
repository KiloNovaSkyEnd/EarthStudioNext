"""Offline tests for data identity, hemisphere masking and night navigation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import from_bounds
from pyresample import create_area_def
from ges.earth_validation.project import save
from ges.earth_validation.night_background import build_vrt,expected_bounds,read_on_area,TILE_IDS,validate_tile
from ges.earth_validation.stock import open_scene,align_sensor,validate_compute_chunk
from ges.earth_validation.fusion import fuse


class StockTests(unittest.TestCase):
    def test_execution_chunk_options_do_not_accept_implicit_quality_changes(self):
        for value in (512,1024,2048):self.assertEqual(validate_compute_chunk(value),value)
        for value in (True,256,1024.0,'1024',4096):
            with self.assertRaises(ValueError):validate_compute_chunk(value)
    def test_native_tile_crop_keeps_red_samples_when_bbox_misses_ir_pixel_edges(self):
        import xarray as xr
        import dask.array as da
        from satpy import Scene
        scene=Scene()
        area=create_area_def('fixture',{'proj':'geos','lon_0':140.7,'h':35785863,
            'a':6378137,'b':6356752.31414,'sweep':'y'},shape=(64,64),
            area_extent=(-16000,-16000,16000,16000),units='m')
        for name,size,res in [('B03',64,500),('B01',32,1000),('B13',16,2000)]:
            values=np.arange(size*size,dtype=np.float32).reshape(size,size)
            scene[name]=xr.DataArray(da.from_array(values,chunks=(8,8)),dims=('y','x'),
                attrs={'name':name,'area':area.copy(width=size,height=size),'resolution':res})
        target=area[slice(13,45),slice(15,47)]
        result,actual=align_sensor(scene,target,native_tile=True)
        red=result['B03'].compute().values
        self.assertEqual(actual.shape,red.shape)
        self.assertGreaterEqual(red.shape[0],32)
        for name in ('B01','B13'):
            np.testing.assert_array_equal(result[name].x,result['B03'].x)
            np.testing.assert_array_equal(result[name].y,result['B03'].y)
        np.testing.assert_array_equal(np.diff(red,axis=1),1)
        np.testing.assert_array_equal(np.diff(red,axis=0),64)
    def test_overlap_blends_only_real_valid_pixels_in_linear_light(self):
        lon=np.array([[-10.,0.,10.,100.]])
        lat=np.zeros_like(lon)
        red=np.array([[[255,0,0,255]]*4],dtype=np.uint8)
        blue=np.array([[[0,0,255,255]]*4],dtype=np.uint8)
        red[0,3]=0; blue[0,3]=0
        rgb,owner,weights=fuse([(red,-10),(blue,10)],lon,lat)
        np.testing.assert_array_equal(rgb[0,0],red[0,0])
        np.testing.assert_array_equal(rgb[0,2],blue[0,2])
        np.testing.assert_array_equal(rgb[0,1],[188,0,188,255])
        self.assertEqual(weights[0,1],.5)
        self.assertEqual(owner[0,3],0); self.assertEqual(rgb[0,3,3],0)

    def test_numpy_reader_metadata_commits_atomically(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'meta.json'
            save(path,{'wavelength':[np.float32(.6),np.int64(1)],'valid':np.bool_(True)})
            record=json.loads(path.read_text())
            self.assertTrue(record['valid']); self.assertEqual(record['wavelength'][1],1)
            before=path.read_bytes()
            with self.assertRaises(TypeError): save(path,{'unknown':object()})
            self.assertEqual(path.read_bytes(),before)

    def test_historical_seviri_is_not_silently_given_fake_rgb(self):
        with self.assertRaisesRegex(ValueError,'no approved stock'):
            open_scene('.',{'records':[]},{'sensor':'meteosat_zero','scene_id':'fixture'})

    def test_global_background_refuses_missing_or_duplicate_tiles(self):
        with self.assertRaisesRegex(ValueError,'all eight'):
            build_vrt('unused.vrt',[{'tile':'D1'}]*8)

    def test_eight_tile_navigation_orientation_and_native_values(self):
        with TemporaryDirectory() as tmp:
            entries=[]
            for number,tile in enumerate(TILE_IDS,1):
                path=Path(tmp)/f'{tile}.tif'; bounds=expected_bounds(tile)
                with rasterio.open(path,'w',driver='GTiff',width=21600,height=21600,count=3,
                    dtype='uint8',crs='EPSG:4326',transform=from_bounds(*bounds,21600,21600),
                    tiled=True,compress='deflate',SPARSE_OK=True) as out:
                    # Sparse TIFF metadata plus a single real RGB pixel; no GB fixture.
                    out.write(np.full((3,1,1),number,np.uint8),window=Window(10800,10800,1,1))
                validate_tile(path,tile); entries.append({'tile':tile,'file':str(path)})
            vrt=build_vrt(Path(tmp)/'global.vrt',entries)
            with rasterio.open(vrt) as src:
                self.assertEqual(src.shape,(43200,86400))
                for number,tile in enumerate(TILE_IDS,1):
                    col='ABCD'.index(tile[0])*21600+10800
                    row=(int(tile[1])-1)*21600+10800
                    np.testing.assert_array_equal(src.read(window=Window(col,row,1,1)),number)
            # D1 pixel center round-trip: geographic warp must select exactly it.
            center_lon=90+(10800+.5)/240
            center_lat=90-(10800+.5)/240
            half=1/480
            area=create_area_def('fixture','EPSG:4326',shape=(1,1),
                area_extent=(center_lon-half,center_lat-half,center_lon+half,center_lat+half))
            np.testing.assert_array_equal(read_on_area(vrt,area),4)


if __name__=='__main__': unittest.main()
