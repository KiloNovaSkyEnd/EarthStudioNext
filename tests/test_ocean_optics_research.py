import unittest
import numpy as np
from scripts.prepare_hinnamnor_ocean_rrs import rgb_equivalent_probe


class OceanOpticsProbeTests(unittest.TestCase):
    def test_missing_negative_and_no_observation_stay_unsupported_without_mutation(self):
        data=np.full((2,3,6),.004,np.float32);n=np.full((2,3),8.)
        data[0,0,1]=np.nan;data[0,1,5]=-.0001;n[1,2]=0
        original=data.copy();data.flags.writeable=False;n.flags.writeable=False
        rgb,support=rgb_equivalent_probe(data,n)
        np.testing.assert_array_equal(data,original)
        self.assertFalse(support[0,0]);self.assertFalse(support[0,1]);self.assertFalse(support[1,2])
        self.assertTrue(np.all(rgb[~support]==0));self.assertTrue(np.isfinite(rgb).all())

    def test_uniform_observations_never_create_spatial_texture(self):
        data=np.full((9,11,6),.003,np.float32);rgb,support=rgb_equivalent_probe(data,np.ones((9,11)))
        self.assertTrue(support.all());self.assertEqual(len(np.unique(rgb.reshape(-1,3),axis=0)),1)
        for wrong in [data[:,:,:3],data[:2]]:
            with self.assertRaises(ValueError):rgb_equivalent_probe(wrong,np.ones((9,11)))
