import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import netCDF4
import numpy as np
from ges.cloud_evidence import evidence_classes,evidence_rgba,_values,low_tint_weight


class EvidenceTests(unittest.TestCase):
    def test_real_china_probable_low_clouds_are_preserved_with_confidence(self):
        from ges.multispectral import night_layers
        with np.load(Path(__file__).parent/'fixtures'/'ahi_china_probable_low_20201029.npz') as d:
            c=evidence_classes(*[d[k] for k in ['CloudMask','CloudPhase','CldTopPres','PcError',
                                              'CloudMaskQualFlag','CloudPhaseFlag','CloudHgtQF']])
            _,_,_,low,_=night_layers(d['longwave'],d['shortwave'],d['Latitude'],-30,-30)
            self.assertEqual(int(((c==6)&(low>.3)).sum()),3779)
            rgba=evidence_rgba(d['longwave'],c,np.ones(c.shape,dtype=bool),
                               low_tint_weight(c),d['Latitude'],low)
            blue=(rgba[...,2]>rgba[...,0])&(rgba[...,3]>0)
            self.assertTrue((blue&(c==6)).any())
            self.assertFalse((blue&~np.isin(c,[2,6])).any())
            self.assertTrue((d['CloudMask'][c==6]==2).all())
            self.assertGreater(float((d['CldTopPres']-d['PcError'])[c==6].min()),680)

    def test_real_legacy_singleton_quality_dimension_and_fill(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'legacy.nc'
            with netCDF4.Dataset(path,'w') as d:
                for name,size in [('Rows',2),('Columns',3),('Flag',1)]:d.createDimension(name,size)
                v=d.createVariable('CloudPhaseFlag','i1',('Rows','Columns','Flag'),fill_value=-128)
                v[:]=np.array([0,1,-128,0,0,0],dtype=np.int8).reshape(2,3,1)
            with netCDF4.Dataset(path) as d:a=_values(d,'CloudPhaseFlag')
            self.assertEqual(a.shape,(2,3));self.assertTrue(np.isnan(a[0,2]))

    def test_real_ahi_crop_has_low_water_and_high_ice_without_clear_blue(self):
        root=Path(__file__).parent/'fixtures'
        with np.load(root/'ahi_l2_cloud_evidence_20201029.npz') as data:
            c=evidence_classes(data['CloudMask'],data['CloudPhase'],data['CldTopPres'],data['PcError'],
                               data['CloudMaskQualFlag'],data['CloudPhaseFlag'],data['CloudHgtQF'])
            self.assertTrue((c==2).any());self.assertTrue((c==5).any())
            self.assertFalse(((c==2)&(data['CloudMask']!=3)).any())
            self.assertGreater(float(np.min((data['CldTopPres']-data['PcError'])[c==2])),680)
            self.assertTrue(np.isin(data['CloudPhase'][c==2],[1,2]).all())
        stats=json.loads((root/'ahi_l2_cloud_evidence_20201029.json').read_text())
        self.assertEqual(stats['pressure_and_error_units'],'hPa')
    def test_clear_and_probably_clear_stay_neutral_while_supported_probable_cloud_is_blue(self):
        c=evidence_classes(np.array([0,1,2]),np.array([0,1,1]),np.array([900]*3),np.array([10]*3),
                           np.zeros(3),np.zeros(3),np.zeros(3))
        np.testing.assert_array_equal(c,[1,4,6])
        rgba=evidence_rgba(np.array([290]*3),c,np.ones(3,dtype=bool))
        np.testing.assert_array_equal(rgba[...,2]>rgba[...,0],[False,False,True])

    def test_probable_mask_needs_all_other_low_liquid_evidence(self):
        mask=np.array([2,2,2,2,2,1,0,3])
        phase=np.array([1,4,1,1,1,1,0,1])
        pressure=np.array([800,800,650,800,800,800,800,800])
        phase_q=np.array([0,0,0,1,0,0,0,0])
        height_q=np.array([0,0,0,0,1,0,0,0])
        c=evidence_classes(mask,phase,pressure,np.full(8,20),np.zeros(8),phase_q,height_q)
        np.testing.assert_array_equal(c,[6,4,4,4,4,4,1,2])
        blue=evidence_rgba(np.full(8,275),c,np.ones(8,dtype=bool))
        np.testing.assert_array_equal(blue[:,2]>blue[:,0],[True,False,False,False,False,False,False,True])

    def test_neutral_ir_has_no_classification_steps_or_fixed_gray_floor(self):
        k=np.array([240,240,240,240,240,290,293.15],dtype=np.float32)
        c=np.array([0,1,3,4,5,3,3])
        rgba=evidence_rgba(k,c,np.ones(7,dtype=bool))
        self.assertTrue((rgba[:5,3]==rgba[0,3]).all())
        self.assertLess(rgba[5,3],5);self.assertEqual(rgba[6,3],0)
        low=evidence_rgba(np.array([270,280,290]),np.full(3,2),np.ones(3,dtype=bool))
        self.assertGreater(low[0,3],low[1,3]);self.assertGreater(low[1,3],low[2,3])

    def test_tint_feather_stays_inside_evidence_without_blurring_ir(self):
        c=np.ones((24,24),dtype=np.uint8);c[:,4:20]=2
        w=low_tint_weight(c,4)
        self.assertFalse(w[c!=2].any());self.assertTrue((w[:,4]>0).all())
        self.assertEqual(w[12,10],1);self.assertGreater(w[12,7],w[12,5])

    def test_original_spectral_transfer_and_no_gray_ocean_veil(self):
        from ges.multispectral import night_layers
        k=np.array([295,285,279,260,220],dtype=np.float32)
        _,_,_,low,high=night_layers(k,k-3,0,-20,-20)
        neutral=evidence_rgba(k,np.full(5,3),np.ones(5,dtype=bool),low_signal=low)
        np.testing.assert_array_equal(neutral[:,3],np.rint(high*255).astype(np.uint8))
        self.assertFalse(neutral[:2,3].any())
        original,*_=night_layers(k,k-3,0,-20,-20)
        supported=evidence_rgba(k,np.full(5,2),np.ones(5,dtype=bool),low_signal=low)
        np.testing.assert_array_equal(supported,original)

    def test_pressure_uncertainty_and_phase_both_constrain_low_cloud(self):
        c=evidence_classes(np.full(6,3),np.array([1,1,1,2,3,4]),np.array([780,700,710,780,900,900]),
                           np.array([50,30,30,50,10,10]),np.zeros(6),np.zeros(6),np.zeros(6))
        np.testing.assert_array_equal(c,[2,3,3,2,3,3])  # exactly 680 is not low.
        rgba=evidence_rgba(np.full(6,270),c,np.ones(6,dtype=bool))
        blue=rgba[:,2]>rgba[:,0]
        np.testing.assert_array_equal(blue,[True,False,False,True,False,False])

    def test_missing_or_bad_quality_does_not_activate_low_cloud(self):
        p=np.array([900,900,900,np.nan,900,900,900])
        e=np.array([10]*6+[-1])
        c=evidence_classes(np.full(7,3),np.ones(7),p,e,np.array([0,1,0,0,0,0,0]),
                           np.array([0,0,1,0,0,0,0]),np.array([1,0,0,0,1,2,0]))
        self.assertFalse((c==2).any())

    def test_high_ice_is_not_mixed_cloud_or_convection_class(self):
        c=evidence_classes(np.full(4,3),np.array([4,4,3,1]),np.array([300,420,200,300]),
                           np.array([40,30,20,20]),np.zeros(4),np.zeros(4),np.zeros(4))
        np.testing.assert_array_equal(c,[5,3,3,3])

    def test_missing_ir_and_daylight_stay_transparent(self):
        rgba=evidence_rgba(np.array([290,np.nan,240,290]),np.array([2,2,5,2]),np.array([True,True,False,False]))
        self.assertGreater(rgba[0,3],0);self.assertFalse(rgba[1:,3].any())

    def test_conflicting_clear_mask_is_unknown_and_shapes_are_checked(self):
        self.assertEqual(evidence_classes(np.array([0]),np.array([1]),np.array([900]),np.array([10]),
                         np.array([0]),np.array([0]),np.array([0]))[0],4)
        with self.assertRaises(ValueError):evidence_classes(np.array([3]),np.array([1,2]),*[np.array([0])]*5)
        with self.assertRaises(ValueError):evidence_rgba(np.ones(2),np.ones(3),np.ones(2))
