import unittest
import numpy as np
from ges_next.algorithms.night_modes import recipe,signature,compose,reduce_night_chroma,neutral_ground_background

class NightModes(unittest.TestCase):
    def test_optional_catalog_keeps_default_six_band_catalog(self):
        from datetime import datetime,timezone
        from types import SimpleNamespace
        from ges_next.algorithms.night_catalog import probe_for
        from ges_next.noaa import AHI_BANDS
        when=datetime(2026,10,20,8,20,tzinfo=timezone.utc)
        candidate=SimpleNamespace(instrument='ahi',satellite='himawari9')
        class Client:
            def get_paginator(self,name):return self
            def paginate(self,**kwargs):
                if kwargs['Prefix'].endswith('/0820/'):
                    yield {'Contents':[dict(Key=kwargs['Prefix']+f'HS_H09_20261020_0820_{band}_FLDK_R20_S{segment:02d}10.DAT.bz2',Size=100,ETag='pinned') for band in recipe({'NightMode':'ai-vis'}).bands for segment in range(1,11)]}
                else:yield {'Contents':[]}
        self.assertEqual(len(probe_for({})(Client(),candidate,when)['keys']),60)
        self.assertEqual(len(probe_for({'NightMode':'ai-vis'})(Client(),candidate,when)['keys']),120)
        self.assertEqual(len(AHI_BANDS),6)
    def test_legacy_default_preserves_identity(self):
        self.assertIsNone(signature({}))
        self.assertEqual(recipe({}).bands,('B01','B02','B03','B04','B07','B13'))
    def test_modes_are_distinct_and_require_complete_inputs(self):
        self.assertNotEqual(signature({'NightMode':'ai-vis'}),signature({'NightMode':'ai-vis-ir'}))
        self.assertEqual(len(recipe({'NightMode':'ai-vis'}).bands),12)
        with self.assertRaises(ValueError):recipe({'NightMode':'other'})
    def test_chroma_preserves_luminance_and_warm_lamps(self):
        colors=np.array([[[.01,.02,.08],[.8,.4,.1],[.5,.5,.5]]],np.float32)
        coeff=np.array([.2126,.7152,.0722],np.float32)
        np.testing.assert_allclose(reduce_night_chroma(colors)@coeff,colors@coeff,atol=1e-7)
        fixed=neutral_ground_background(colors)
        np.testing.assert_array_equal(fixed[:,1:],colors[:,1:])
        self.assertLess(float(fixed[0,0,2]-fixed[0,0,0]),float(colors[0,0,2]-colors[0,0,0]))
    def test_full_day_identity_and_support(self):
        rng=np.random.default_rng(7);day=rng.random((4,5,3),dtype=np.float32);night=rng.random((4,5,3),dtype=np.float32)
        for mode in ('ai-vis','ai-vis-ir'):
            out=compose(day,night,np.ones((4,5),np.float32),np.zeros((4,5),np.float32),np.ones((4,5),bool),mode)
            np.testing.assert_array_equal(out,day)
            out=compose(day,night,np.zeros((4,5),np.float32),np.ones((4,5),np.float32),np.zeros((4,5),bool),mode)
            self.assertEqual(np.count_nonzero(out),0)
