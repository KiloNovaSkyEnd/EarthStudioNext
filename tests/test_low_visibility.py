import unittest
from pathlib import Path
import numpy as np
from ges.cloud_evidence import evidence_rgba,evidence_classes,supported_low_visibility,LOW_CLASSES
from ges.multispectral import night_layers


class LowVisibilityTests(unittest.TestCase):
    def test_missing_shortwave_does_not_erase_existing_low_evidence(self):
        k=np.array([285,285],dtype=np.float32)
        _,_,night,low,_=night_layers(k,np.full(2,np.nan),0,-20,-20)
        out=evidence_rgba(k,np.array([2,4]),night,low_signal=low)
        self.assertGreater(out[0,3],0);self.assertGreater(out[0,2],out[0,0])
        self.assertEqual(out[1,3],0)

    def test_supported_weak_spectral_clouds_visible_but_clear_not_blue(self):
        k=np.array([275,285,295,285,285,285,np.nan],dtype=np.float32)
        c=np.array([2,6,7,1,4,9,2]);night=np.array([1,1,1,1,1,0,1],dtype=bool)
        out=evidence_rgba(k,c,night,low_signal=np.zeros(7))
        blue=(out[:,2]>out[:,0])&(out[:,3]>0)
        np.testing.assert_array_equal(blue,[1,1,1,0,0,0,0])
        self.assertGreater(out[0,3],out[1,3]);self.assertGreater(out[1,3],out[2,3])

    def test_original_strong_signal_and_non_supported_pixels_unchanged(self):
        k=np.array([260,275,285,295],dtype=np.float32);signal=np.full(4,.9,dtype=np.float32)
        np.testing.assert_array_equal(supported_low_visibility(k,signal),signal)
        out=evidence_rgba(k,np.full(4,3),np.ones(4,dtype=bool),low_signal=np.zeros(4))
        _,_,_,_,high=night_layers(k,k,0,-20,-20)
        np.testing.assert_array_equal(out[:,3],np.rint(high*255).astype(np.uint8))
        self.assertFalse((out[:,2]>out[:,0]).any())

    def test_real_china_supported_crop_retains_weak_signal_clouds(self):
        p=Path(__file__).parent/'fixtures/ahi_china_weak_btd_low_20201029.npz'
        with np.load(p) as d:
            c=evidence_classes(*[d[k] for k in ['CloudMask','CloudPhase','CldTopPres','PcError',
                                              'CloudMaskQualFlag','CloudPhaseFlag','CloudHgtQF']],nominal_low=True)
            _,_,_,low,_=night_layers(d['longwave'],d['shortwave'],d['Latitude'],-30,-30)
            out=evidence_rgba(d['longwave'],c,np.ones(c.shape,dtype=bool),latitude=d['Latitude'],low_signal=low)
            supported=np.isin(c,LOW_CLASSES);blue=(out[...,2]>out[...,0])&(out[...,3]>0)
            self.assertTrue((supported&(low==0)).any())
            self.assertTrue(blue[supported&(low==0)].all())
            self.assertFalse((blue&~supported).any())
