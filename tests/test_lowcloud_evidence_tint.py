import unittest
import numpy as np
from ges.goni_lowcloud import spectral_night_material,evidence_tinted_night_material,low_liquid_confidence,screen_confident_clear


class EvidenceTintTests(unittest.TestCase):
    def test_clear_screen_is_not_a_probability_threshold_or_mutation(self):
        p=np.array([.2,.2,.6,.99,.2]);m=np.array([0,1,2,3,0]);q=np.array([0,0,0,0,1]);old=p.copy()
        out=screen_confident_clear(p,m,q)
        np.testing.assert_array_equal(out,[0,.2,.6,.99,.2]);np.testing.assert_array_equal(p,old)
        with self.assertRaises(ValueError):screen_confident_clear(p,m[:-1],q)
    def test_signed_observed_btd_controls_tint_without_changing_cloud_opacity(self):
        t=np.full(6,280.);sw=t-np.array([-2.,0.,1.,2.,4.,6.]);p=np.full(6,.9);low=np.ones(6);night=np.ones(6,bool)
        rgb,alpha=evidence_tinted_night_material(t,sw,p,low,night)
        _,old=spectral_night_material(t,sw,p,low,night,low_cloud_tint_strength=.85)
        np.testing.assert_array_equal(alpha,old)
        chroma=rgb[:,2]-rgb[:,0];np.testing.assert_array_equal(chroma[:2],[0,0])
        self.assertTrue(np.all(np.diff(chroma[1:5])>0));self.assertTrue(np.all(alpha>0))

    def test_missing_or_sun_contaminated_shortwave_uses_legacy_lw_fallback(self):
        t=np.array([280.,280.,280.]);sw=np.array([np.nan,275.,50.]);p=np.ones(3);low=np.ones(3);night=np.array([True,False,True])
        a=evidence_tinted_night_material(t,sw,p,low,night)
        b=spectral_night_material(t,sw,p,low,night,low_cloud_tint_strength=.85)
        for x,y in zip(a,b):np.testing.assert_array_equal(x,y)

    def test_bad_low_class_never_creates_blue_or_erases_neutral_cloud(self):
        confidence=low_liquid_confidence(np.full(4,3),np.zeros(4),np.array([1,4,1,1]),np.array([0,0,1,0]),
                                          np.array([1,1,1,8]),np.ones(4)*.5,np.zeros(4))
        rgb,alpha=evidence_tinted_night_material(np.full(4,280.),np.full(4,276.),np.ones(4),confidence,np.ones(4,bool))
        np.testing.assert_array_equal(confidence,[1,0,0,0]);self.assertGreater(rgb[0,2],rgb[0,0])
        np.testing.assert_array_equal(rgb[1:,2],rgb[1:,0]);self.assertTrue(np.all(alpha>0))
