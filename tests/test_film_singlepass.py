import unittest
import numpy as np
from ges.film_singlepass import single_handoff
from ges.film_transition import cloud_day_weight


class SingleSolarTests(unittest.TestCase):
    def test_one_solar_mix_not_two_successive_cloud_fades(self):
        day=np.full((1,1,3),255,np.uint8);night=np.zeros((1,1,4),np.uint8)
        ground=np.zeros_like(day);context=np.full((1,1,4),255,np.uint8)
        out=single_handoff(day,night,ground,context,.5,1)
        # Linear-light halfway black/white is 188, independent of the coarse
        # VIS/static context. A second solar mix would bias this toward white.
        np.testing.assert_array_equal(out[0,0],[188,188,188,255])

    def test_no_jump_at_day_side_transition_start_or_end(self):
        angles=np.array([[5.738,5.739,5.740,17.457,17.458,17.459]])
        s=cloud_day_weight(angles,'solar-sine-c2')
        day=np.full((1,6,3),220,np.uint8);n=np.full((1,6,4),100,np.uint8)
        g=np.full_like(day,10);context=np.full_like(n,180)
        out=single_handoff(day,n,g,context,s,1)
        self.assertLessEqual(abs(np.diff(out[0,:3,0].astype(int))).max(),1)
        self.assertLessEqual(abs(np.diff(out[0,3:,0].astype(int))).max(),1)

    def test_rgb_missing_preserves_context_exactly_at_all_solar_angles(self):
        c=np.array([[[30,50,70,255],[140,191,250,255]]],np.uint8)
        out=single_handoff(np.zeros((1,2,3),np.uint8),np.zeros_like(c),np.zeros((1,2,3),np.uint8),c,np.array([[0,1]]),0)
        np.testing.assert_array_equal(out,c)

    def test_solar_curve_is_global_monotonic_and_rejects_unknown_profile(self):
        angles=np.linspace(-90,90,18001);w=cloud_day_weight(angles,'solar-sine-c2')
        self.assertTrue((np.diff(w)>=0).all());self.assertFalse(w[angles<=5].any())
        self.assertTrue((w[angles>=18]==1).all())
        with self.assertRaises(ValueError):cloud_day_weight(angles,'unknown')
