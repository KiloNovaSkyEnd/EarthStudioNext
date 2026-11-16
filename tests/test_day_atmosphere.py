import unittest
import numpy as np
from ges.day_atmosphere import correction_strength,corrected_rgb,geocolor_day_weight
from ges.day_night import compose_pixels
from ges.day_night import transition_ir


class FakeRayleigh:
    def get_reflectance(self,sunz,satz,azimuth,band):
        return np.full_like(sunz,10 if band=='C01' else 2)


class AtmosphereTests(unittest.TestCase):
    def test_twilight_warm_cloud_requires_existing_class_and_never_uses_blue(self):
        old=np.zeros((1,3,4),np.uint8);lw=np.full((1,3),290,dtype=np.float32)
        classes=np.array([[0,2,9]],np.uint8)
        out=transition_ir(old,lw,0,0,0,classes=classes)
        self.assertEqual(out[0,0,3],0)
        self.assertTrue((out[0,1:,3]>0).all())
        np.testing.assert_array_equal(out[...,0],out[...,2])
        night=transition_ir(old,lw,-15,-14,0,classes=classes)
        np.testing.assert_array_equal(night,old)

    def test_published_cold_cloud_path_bounds_and_limb_reduction(self):
        np.testing.assert_allclose(correction_strength(np.array([200,233,258,283,300]),0),[.3,.3,.65,1,1])
        self.assertEqual(correction_strength(290,85),0)

    def test_published_solar_transition_has_day_side_bounds(self):
        elev=np.rad2deg(np.arcsin(np.array([0,.1,.2,.3,1])))
        np.testing.assert_allclose(geocolor_day_weight(elev),[0,0,.5**1.5,1,1],atol=1e-7)
        x=geocolor_day_weight(np.linspace(-90,90,3601))
        self.assertTrue((np.diff(x)>=0).all());self.assertLess(abs(np.diff(x)).max(),.008)

    def test_cold_cloud_does_not_get_clear_sky_overcorrection(self):
        a=np.full((1,2),.4,dtype=np.float32)
        out,_,_=corrected_rgb(a,a,a,np.array([[230,290]]),90,90,90,np.zeros_like(a),np.zeros_like(a),FakeRayleigh())
        self.assertGreater(out[0,0,2],out[0,1,2])
        self.assertTrue((out[...,3]==255).all())

    def test_missing_or_night_vis_never_restored_by_correction(self):
        b=np.array([[np.nan,.3,.3]],dtype=np.float32);r=np.full_like(b,.3)
        out,_,_=corrected_rgb(b,r,r,np.full_like(b,270),10,np.array([[10,-1,10]]),np.array([[10,10,-1]]),np.zeros_like(b),np.zeros_like(b),FakeRayleigh())
        self.assertFalse(out.any())

    def test_explicit_measured_ir_fallback_no_visible_or_reference_invention(self):
        day=np.zeros((1,3,4),np.uint8);cloud=np.full_like(day,255)
        out,dw,nw=compose_pixels(day,cloud,np.zeros((1,3,3),np.uint8),np.ones((1,3)),np.array([[True,False,True]]),ir_fallback=True)
        np.testing.assert_array_equal(out[0,:,3],[255,0,255]);self.assertFalse(dw.any())
        np.testing.assert_array_equal(nw,[[1,0,1]])
        np.testing.assert_array_equal(out[0,0,:3],[255,255,255])

    def test_real_rejected_bright_cloud_fixture_stays_invalid_vis_and_uses_ir(self):
        from pathlib import Path
        from ges.daylight import abi_rgb
        with np.load(Path(__file__).parent/'fixtures/abi_bright_rejected_20201029.npz') as f:
            bands=[np.where(f['DQF_'+b]==0,f[b],np.nan) for b in ['C01','C02','C03']]
            day,_,_=abi_rgb(*bands,90,90,90)
            rejected=(day[...,3]==0)&np.isfinite(f['C13'])&(f['C13']<230)
            self.assertGreater(int(rejected.sum()),10)
            cloud=np.full_like(day,255)
            out,dw,nw=compose_pixels(day,cloud,np.zeros(day.shape[:-1]+(3,),np.uint8),np.ones(day.shape[:2]),np.isfinite(f['C13']),ir_fallback=True)
            self.assertTrue((out[rejected,3]==255).all());self.assertFalse(dw[rejected].any())
            self.assertTrue((nw[rejected]==1).all())


if __name__=='__main__':unittest.main()
