import unittest
from pathlib import Path
import numpy as np
from ges.cloud_evidence import evidence_rgba,low_cloud_texture,evidence_classes,LOW_CLASSES


class LowTextureTests(unittest.TestCase):
    def test_previously_saturated_btd_retains_observed_contrast(self):
        lw=np.full(4,285,dtype=np.float32);sw=lw-np.array([4.5,5,6,8])
        out=evidence_rgba(lw,np.full(4,2),np.ones(4,dtype=bool),low_shortwave=sw)
        self.assertTrue((np.diff(out[:,3].astype(int))>0).all())
        self.assertTrue((out[:,3]<255).all())

    def test_weak_cloud_color_has_measured_lw_shading(self):
        lw=np.array([281,287,293],dtype=np.float32)
        out=evidence_rgba(lw,np.full(3,2),np.ones(3,dtype=bool),low_shortwave=lw)
        self.assertTrue((np.diff(out[:,2].astype(int))<0).all())
        self.assertTrue((out[:,2]>out[:,0]).all());self.assertTrue((out[:,3]>0).all())

    def test_signed_weak_btd_is_not_a_flat_thermal_patch(self):
        lw=np.full(5,285,dtype=np.float32);sw=lw-np.array([-3,-2,-1,0,1])
        out=evidence_rgba(lw,np.full(5,2),np.ones(5,dtype=bool),low_shortwave=sw)
        self.assertTrue((np.diff(out[:,3].astype(int))>0).all())
        self.assertTrue((out[:,3]>0).all())

    def test_no_support_day_missing_ir_and_neutral_are_unchanged(self):
        lw=np.array([275,285,270,np.nan,285],dtype=np.float32)
        classes=np.array([3,1,2,2,2]);night=np.array([1,1,0,1,1],dtype=bool)
        old=evidence_rgba(lw,classes,night,low_signal=np.zeros(5))
        new=evidence_rgba(lw,classes,night,low_signal=np.zeros(5),low_shortwave=np.full(5,np.nan))
        np.testing.assert_array_equal(old[:4],new[:4])
        self.assertGreater(new[4,3],0)
        with self.assertRaises(ValueError):low_cloud_texture(lw,np.ones(4))

    def test_real_china_weak_clouds_have_no_new_unsupported_blue(self):
        with np.load(Path(__file__).parent/'fixtures/ahi_china_weak_btd_low_20201029.npz') as d:
            c=evidence_classes(*[d[k] for k in ['CloudMask','CloudPhase','CldTopPres','PcError',
                'CloudMaskQualFlag','CloudPhaseFlag','CloudHgtQF']],nominal_low=True)
            out=evidence_rgba(d['longwave'],c,np.ones(c.shape,dtype=bool),latitude=d['Latitude'],low_shortwave=d['shortwave'])
            blue=(out[...,2]>out[...,0])&(out[...,3]>0)
            self.assertFalse((blue&~np.isin(c,LOW_CLASSES)).any())
            self.assertTrue(blue[np.isin(c,LOW_CLASSES)].all())
            self.assertGreater(np.unique(out[...,2][blue]).size,8)
