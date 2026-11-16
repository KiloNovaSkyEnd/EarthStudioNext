import unittest
from pathlib import Path
import numpy as np
from ges.daylight import abi_rgb
from ges.day_night import transition_ir,compose_pixels,verify_lw_interval


class DayNightTests(unittest.TestCase):
    def test_authentic_abi_reflectance_fixture_retains_good_day_pixels(self):
        with np.load(Path(__file__).parent/'fixtures/abi_daylight_20201029.npz') as d:
            bands=[np.where(d['DQF_'+b]==0,d[b],np.nan) for b in ['C01','C02','C03']]
            out,valid,eligible=abi_rgb(*bands,d['elevation_mid'],d['elevation_start'],d['elevation_end'])
            self.assertGreater(int(eligible.sum()),500)
            expected=np.isfinite(bands[0])&np.isfinite(bands[1])&np.isfinite(bands[2])
            np.testing.assert_array_equal(valid,expected);np.testing.assert_array_equal(out[...,3]>0,eligible)
            self.assertGreater(np.unique(out[...,:3][eligible],axis=0).shape[0],50)

    def test_ahi_lw_detector_interval_must_be_inside_verified_pair_union(self):
        accepted=('2020-10-29T16:40:21.326631Z','2020-10-29T16:49:41.358953Z')
        actual=('2020-10-29T16:40:21.953000Z','2020-10-29T16:49:41.358953Z')
        verify_lw_interval(actual,accepted,'himawari8')
        with self.assertRaises(ValueError):verify_lw_interval(actual,accepted,'goes16')
        with self.assertRaises(ValueError):verify_lw_interval(('2020-10-29T16:40:23Z',actual[1]),accepted,'himawari8')

    def test_declared_green_and_solar_correction(self):
        b=np.array([[.2]]);r=np.array([[.4]]);v=np.array([[.6]])
        out,_,_=abi_rgb(b,r,v,30,29,31)
        expected=np.rint((np.array([.4,.45*.4+.10*.6+.45*.2,.2])/.5)**(1/2.2)*255).astype(np.uint8)
        np.testing.assert_array_equal(out[0,0,:3],expected);self.assertEqual(out[0,0,3],255)

    def test_visible_requires_both_scan_endpoints_and_all_bands(self):
        a=np.full((1,4),.2);bad=a.copy();bad[0,3]=np.nan
        out,_,_=abi_rgb(a,a,bad,10,np.array([[10,-1,10,10]]),np.array([[10,10,-1,10]]))
        np.testing.assert_array_equal(out[...,3],[[255,0,0,0]])

    def test_good_negative_reflectance_is_display_clipped_not_invented_missing(self):
        a=np.array([[-.01,.1]])
        out,valid,_=abi_rgb(a,a,a,90,90,90)
        self.assertTrue(valid.all());self.assertEqual(out[0,0,3],255)
        np.testing.assert_array_equal(out[0,0,:3],[0,0,0])

    def test_day_and_deep_night_endpoints_retain_source_colors(self):
        day=np.array([[[50,100,150,255],[50,100,150,255]]],dtype=np.uint8)
        cloud=np.array([[[140,191,250,100],[140,191,250,100]]],dtype=np.uint8)
        surface=np.full((1,2,3),10,dtype=np.uint8)
        out,_,_=compose_pixels(day,cloud,surface,np.array([[1,0]]),np.ones((1,2),bool))
        np.testing.assert_array_equal(out[0,0],day[0,0])
        expected=np.rint(cloud[0,1,:3]*(100/255)+10*(1-100/255)).astype(np.uint8)
        np.testing.assert_array_equal(out[0,1,:3],expected);self.assertEqual(out[0,1,3],255)

    def test_missing_day_not_replaced_by_opaque_ir(self):
        day=np.zeros((1,3,4),dtype=np.uint8);cloud=np.full((1,3,4),255,dtype=np.uint8)
        out,dw,nw=compose_pixels(day,cloud,np.zeros((1,3,3),dtype=np.uint8),np.array([[1,.5,0]]),np.ones((1,3),bool))
        np.testing.assert_array_equal(out[...,3],[[0,128,255]])
        self.assertFalse(dw.any());np.testing.assert_allclose(nw,[[0,.5,1]])

    def test_missing_night_reference_does_not_become_observed_cloud_coverage(self):
        out,_,_=compose_pixels(np.zeros((1,1,4),np.uint8),np.zeros((1,1,4),np.uint8),
                               np.full((1,1,3),255,np.uint8),np.zeros((1,1)),np.zeros((1,1),bool))
        self.assertFalse(out.any())

    def test_twilight_uses_neutral_measured_ir_and_deep_night_is_exact(self):
        old=np.array([[[140,191,250,150],[0,0,0,0],[0,0,0,0]]],dtype=np.uint8)
        lw=np.array([[270,250,np.nan]],dtype=np.float32)
        out=transition_ir(old,lw,np.array([[-15,-3,-3]]),np.array([[-14,-2,-2]]),0)
        np.testing.assert_array_equal(out[0,0],old[0,0])
        self.assertGreater(out[0,1,3],0);self.assertEqual(out[0,1,0],out[0,1,2]);self.assertFalse(out[0,2].any())

    def test_invalid_weights_and_shape_rejected(self):
        p=np.zeros((1,1,4),np.uint8)
        with self.assertRaises(ValueError):compose_pixels(p,p,np.zeros((1,1,3)),np.array([[np.nan]]),np.ones((1,1),bool))
        with self.assertRaises(ValueError):compose_pixels(p,p,np.zeros((1,2,3)),np.ones((1,1)),np.ones((1,1),bool))
