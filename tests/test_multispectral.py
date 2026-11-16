import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock,patch,MagicMock
from datetime import datetime,timedelta
import json
import netCDF4
import numpy as np
import xarray as xr
from PIL import Image
from ges.multispectral import night_layers, calibrated_pair,render_multispectral,sensor_display_policy


class SpectralTests(unittest.TestCase):
    def test_ahi_subsecond_detector_offset_uses_conservative_actual_union(self):
        nominal=datetime(2020,10,29,16,40);end=nominal+timedelta(minutes=10)
        datasets={}
        for band,um,shift in [('B13',10.4,.95),('B07',3.9,.32)]:
            datasets[band]=xr.DataArray(np.ones((2,2)),attrs={'units':'K','wavelength':SimpleNamespace(central=um),
                'area':'same-source-area','start_time':nominal,'end_time':end,
                'time_parameters':{'observation_start_time':nominal+timedelta(seconds=21+shift),
                                   'observation_end_time':nominal+timedelta(minutes=9,seconds=40+shift)}})
        scene=MagicMock();scene.__getitem__.side_effect=lambda name:datasets[name]
        with patch('ges.multispectral.create_satpy_scene',return_value=scene):
            _,_,start,stop,policies=calibrated_pair({'satellite':'himawari8','local_files':['dummy']})
            self.assertEqual(start,'2020-10-29T16:40:21.320000Z');self.assertEqual(stop,'2020-10-29T16:49:40.950000Z')
            self.assertIn('actual band interval',policies[0])
            datasets['B07'].attrs['time_parameters']['observation_start_time']+=timedelta(seconds=3)
            with self.assertRaises(ValueError):calibrated_pair({'satellite':'himawari8','local_files':['dummy']})
    def test_unverified_seviri_blue_cannot_color_surface(self):
        rgba,_,_,low,high=night_layers([290,240],[280,230],0,-20,-20)
        result,signal=sensor_display_policy(rgba,low,high,'meteosat_msg4')
        self.assertFalse(signal.any());self.assertEqual(result[0,3],0)
        self.assertTrue((result[1,:3]==255).all())
        self.assertEqual(result[1,3],round(float(high[1])*255))
        unchanged,_=sensor_display_policy(rgba,low,high,'himawari8')
        np.testing.assert_array_equal(unchanged,rgba)

    def test_append_preserves_base_and_only_adds_real_coverage(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); base=root/'base'; base.mkdir()
            image=base/'night_multispectral.png'
            pixels=np.zeros((256,512,4),dtype=np.uint8);pixels[:,:256]=[140,191,250,255]
            Image.fromarray(pixels).save(image)
            mask=np.zeros((256,512),dtype=np.uint8);mask[:,:256]=255
            for name in ['night_eligible','low_spectral_signal','paired_band_coverage']:
                Image.fromarray(mask).save(base/f'night_multispectral_{name}.png')
            Image.fromarray((mask>0).astype(np.uint8)).save(base/'night_multispectral_source_index.png')
            Image.fromarray(np.zeros_like(mask)).save(base/'night_multispectral_cold_ir_signal.png')
            meta={'display_recipe':'night-multispectral-experimental-v1','projection':'EPSG:4326',
                  'extent_wsen':[-180,-90,180,90],'width':512,'height':256,'sources':[{'original':True}],
                  'reference_utc':'2020-10-29T16:40:00Z'}
            image.with_suffix('.json').write_text(json.dumps(meta))
            lights=root/'lights.png';Image.new('RGB',(512,256),(10,10,10)).save(lights)
            lights.with_suffix('.json').write_text(json.dumps({
                'kind':'static reference night-lights composite, not contemporaneous with satellite clouds',
                'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':512,'height':256}))
            values=np.full((256,512),290,dtype=np.float32);values[:,400:]=np.nan
            pair={'LW':SimpleNamespace(compute=lambda:SimpleNamespace(values=values)),
                  'SW':SimpleNamespace(compute=lambda:SimpleNamespace(values=values-5))}
            scene=Mock();scene.resample.return_value=pair
            manifest=root/'raw'/'scene.json'
            with patch('ges.multispectral.read_manifest',return_value={'observed_utc':meta['reference_utc']}), \
                 patch('ges.multispectral.calibrated_pair',return_value=(scene,('LW','SW'),meta['reference_utc'],meta['reference_utc'],[])):
                out=render_multispectral([manifest],lights,root/'derived',512,image)
            rendered=np.asarray(Image.open(out));indices=np.asarray(Image.open(out.parent/'night_multispectral_source_index.png'))
            np.testing.assert_array_equal(rendered[:,:256],pixels[:,:256])
            self.assertTrue((indices[:,:256]==1).all());self.assertTrue((indices[:,256:400]==2).all())
            self.assertTrue((indices[:,400:]==0).all());self.assertFalse(rendered[:,400:,3].any())
            result=json.loads(out.with_suffix('.json').read_text())
            self.assertEqual(result['sources'][0],{'original':True})
            self.assertEqual(result['reference_utc'],meta['reference_utc'])

    def test_real_two_band_calibration_and_independent_quality(self):
        path=next((Path(__file__).parent/'fixtures'/'goes_multispectral').glob('*.nc'))
        scene,bands,start,end,policies=calibrated_pair({'satellite':'goes16','local_files':[str(path)]})
        self.assertEqual(bands,('C13','C07'))
        self.assertEqual(start,'2020-10-29T16:40:18.900000Z')
        self.assertEqual(end,'2020-10-29T16:49:50.800000Z')
        with netCDF4.Dataset(path) as raw:
            for band,policy in zip(bands,policies):
                good=np.ma.filled(raw[f'DQF_{band}'][:],255)==0
                expected=np.ma.filled(raw[f'CMI_{band}'][:],np.nan)
                actual=scene[band].compute().values
                self.assertIn('good_pixel_qf only',policy)
                np.testing.assert_allclose(actual[good],expected[good],atol=1e-4)
                self.assertTrue(np.isnan(actual[~good]).all())

    def test_warm_temperature_alone_cannot_make_blue_cloud(self):
        rgba,coverage,night,low,high=night_layers([290,290],[290,285],0,-20,-20)
        self.assertTrue(coverage.all()); self.assertTrue(night.all())
        self.assertEqual(rgba[0,3],0)
        np.testing.assert_array_equal(rgba[1],[140,191,250,255])
        np.testing.assert_array_equal(low,[0,1])
        np.testing.assert_array_equal(high,[0,0])

    def test_cold_cloud_shortwave_noise_does_not_activate_blue(self):
        rgba,_,_,low,high=night_layers([200,229],[150,200],0,-20,-20)
        np.testing.assert_array_equal(low,[0,0])
        np.testing.assert_array_equal(rgba[0],[255,255,255,255])
        self.assertGreater(high[1],0)
        self.assertTrue((rgba[1,:3] == 255).all())

    def test_both_scan_endpoints_must_be_night_and_coverage_is_separate(self):
        rgba,coverage,night,_,_=night_layers([290]*4,[285]*4,0,[-10,-5,-10,-10],[-10,-10,5,-6])
        self.assertTrue(coverage.all())
        np.testing.assert_array_equal(night,[True,False,False,True])
        np.testing.assert_array_equal(rgba[:,3],[255,0,0,255])

    def test_missing_bands_disable_blue_without_discarding_real_longwave(self):
        with np.errstate(invalid='raise'):
            rgba,coverage,night,low,high=night_layers([290,np.nan,400,290],[np.nan,285,285,50],0,-20,-20)
        np.testing.assert_array_equal(coverage,[True,False,False,True])
        self.assertFalse(rgba.any()); self.assertFalse(low.any()); self.assertFalse(high.any())
        rgba,coverage,night,low,high=night_layers([200,np.nan],[np.nan,200],0,-20,-20)
        np.testing.assert_array_equal(rgba[0],[255,255,255,255])
        self.assertFalse(rgba[1].any()); self.assertFalse(low.any())
        np.testing.assert_array_equal(coverage,[True,False])

    def test_latitude_symmetric_and_cold_overrides_low_layer(self):
        rgba,_,_,low,high=night_layers([260]*3,[255]*3,[60,-60,0],-20,-20)
        np.testing.assert_array_equal(rgba[0],rgba[1])
        self.assertGreater(high[0],high[2])
        self.assertEqual(low[0],1)
        self.assertGreater(rgba[0,0],140)
        self.assertGreater(rgba[0,2],rgba[0,0])


if __name__=='__main__': unittest.main()
