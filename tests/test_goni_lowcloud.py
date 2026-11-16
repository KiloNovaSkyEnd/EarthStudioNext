import unittest
import numpy as np
from ges.goni_lowcloud import low_liquid_confidence,night_material,spectral_night_material,daylight_material


class LowCloudRestorationTests(unittest.TestCase):
    def test_daylight_retains_bright_cloud_tone_and_thick_cloud_opacity(self):
        color,alpha=daylight_material(np.array([0,.02,.8,1.,1.2,1.8]),np.ones(6))
        self.assertEqual(alpha[0],0);self.assertLess(alpha[1],.1)
        self.assertGreater(alpha[2],.98);self.assertTrue(np.all(np.diff(color)>0))
        self.assertLess(color[-1],1)
        _,empty=daylight_material(np.array([.8,1.]),np.zeros(2));np.testing.assert_array_equal(empty,[0,0])

    def test_strict_nominal_and_failed_height_have_separate_tint_confidence(self):
        z=np.zeros(5);mask=np.full(5,3);phase=np.array([1,2,4,1,1])
        confidence=low_liquid_confidence(mask,z,phase,z,np.array([1,2.5,1,4,1]),np.array([.5,1,.5,.5,.5]),np.array([0,0,0,0,1]))
        np.testing.assert_allclose(confidence,[1,.35,0,0,0])

    def test_rejected_low_class_never_erases_other_clouds(self):
        rgb,alpha=night_material(np.array([280,250,210]),np.ones(3),np.zeros(3))
        self.assertTrue(np.all(alpha>0));self.assertTrue(np.all(np.diff(alpha)>0))

    def test_warm_verified_low_cloud_is_visible_and_blue(self):
        rgb,alpha=night_material(np.array([290.]),np.array([.95]),np.array([1.]))
        self.assertGreater(alpha[0],.35);self.assertGreater(rgb[0,2],rgb[0,0])

    def test_probability_varies_continuously_across_old_binary_threshold(self):
        _,a=night_material(np.full(4,270.),np.array([0,.49,.51,1]),np.zeros(4))
        self.assertEqual(a[0],0);self.assertLess(a[2]-a[1],.02)
        np.testing.assert_allclose(a/a[-1],[0,.49,.51,1],atol=1e-6)

    def test_invalid_temperature_or_probability_remains_transparent(self):
        _,alpha=night_material(np.array([np.nan,90,270,270]),np.array([1,1,np.nan,0]),np.ones(4))
        np.testing.assert_array_equal(alpha,np.zeros(4))

    def test_observed_shortwave_restores_texture_without_classifying_clouds(self):
        _,alpha=spectral_night_material(np.full(2,275.),np.array([274.,270.]),np.ones(2),np.ones(2),np.ones(2,bool))
        self.assertGreater(alpha[1]-alpha[0],.15)
        _,neutral=spectral_night_material(np.full(2,275.),np.array([274.,270.]),np.ones(2),np.zeros(2),np.ones(2,bool))
        self.assertEqual(neutral[0],neutral[1]);self.assertGreater(neutral.min(),0)

    def test_day_contaminated_or_missing_sw_falls_back_to_lw(self):
        t=np.array([285.,285.]);p=np.ones(2);low=np.ones(2)
        expected=night_material(t,p,low)
        actual=spectral_night_material(t,np.array([280.,np.nan]),p,low,np.array([False,True]))
        for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)
        _,invalid=spectral_night_material(np.array([np.nan,90.]),np.array([275.,275.]),p,low,np.ones(2,bool))
        np.testing.assert_array_equal(invalid,[0,0])

    def test_tint_candidate_preserves_opacity_and_weighted_display_brightness(self):
        t=np.array([290.,275.,230.,210.,np.nan]);p=np.array([1.,.5,1.,1.,1.]);low=np.array([1.,.35,0.,0.,1.])
        for sw,eligible in [(t-3,np.ones(5,bool)),(np.full(5,np.nan),np.zeros(5,bool))]:
            old,oa=spectral_night_material(t,sw,p,low,eligible)
            new,na=spectral_night_material(t,sw,p,low,eligible,low_cloud_tint_strength=.85)
            np.testing.assert_array_equal(na,oa)
            weights=np.array([.2126,.7152,.0722])
            np.testing.assert_allclose(new@weights,old@weights,atol=1e-7)
            np.testing.assert_allclose(new[:,2]-new[:,0],.85*(old[:,2]-old[:,0]),atol=1e-7)
            np.testing.assert_array_equal(new[low==0],old[low==0])

    def test_tint_candidate_retains_longwave_fallback_and_spectral_contrast(self):
        t=np.full(3,285.);p=np.ones(3);low=np.ones(3)
        expected=night_material(t,p,low,low_cloud_tint_strength=.85)
        fallback=spectral_night_material(t,t-3,p,low,np.zeros(3,bool),low_cloud_tint_strength=.85)
        for a,b in zip(expected,fallback):np.testing.assert_array_equal(a,b)
        _,a=spectral_night_material(t,t-np.array([0.,2.,5.]),p,low,np.ones(3,bool),low_cloud_tint_strength=.85)
        self.assertTrue(np.all(np.diff(a)>0))

    def test_tint_profile_is_opt_in_and_bounded(self):
        t=np.array([280.]);p=np.ones(1)
        for default,explicit in zip(night_material(t,p,p),night_material(t,p,p,low_cloud_tint_strength=1.)):
            np.testing.assert_array_equal(default,explicit)
        for bad in [-1,.79,1.01,np.nan,np.inf,[.85]]:
            with self.assertRaises(ValueError):night_material(t,p,p,low_cloud_tint_strength=bad)
