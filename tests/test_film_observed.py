import unittest
import numpy as np
from ges.film_observed import context_pixels
from ges.film_transition import smoother


class ObservedContextTests(unittest.TestCase):
    def test_missing_observation_shows_reference_never_black_source(self):
        legacy=np.array([[[200,200,200,0]]],np.uint8);g=np.array([[[80,90,100]]],np.uint8)
        out=context_pixels(legacy,g,np.ones((1,1)),np.full((1,1,3),255,np.uint8),np.zeros((1,1)))
        np.testing.assert_array_equal(out[...,:3],g)
        self.assertEqual(out[0,0,3],255)  # presentation geometry only

    def test_central_night_exact_when_rgb_weight_zero(self):
        n=np.array([[[100,140,190,255],[10,20,30,255]]],np.uint8)
        out=context_pixels(n,np.full((1,2,3),40,np.uint8),np.ones((1,2)),np.full((1,2,3),250,np.uint8),np.zeros((1,2)))
        np.testing.assert_array_equal(out,n)

    def test_fully_selected_rgb_is_actual_unmasked_pixel(self):
        rgb=np.array([[[123,180,240]]],np.uint8)
        out=context_pixels(np.zeros((1,1,4),np.uint8),np.zeros((1,1,3),np.uint8),np.zeros((1,1)),rgb,np.ones((1,1)))
        np.testing.assert_array_equal(out[...,:3],rgb)

    def test_grazing_fade_is_continuous_without_copying_clouds_outside_support(self):
        v=np.linspace(.10,.34,24001).reshape(1,-1);q=smoother(v,.12,.32)
        n=np.full(v.shape+(4,),255,np.uint8);g=np.zeros(v.shape+(3,),np.uint8)
        out=context_pixels(n,g,q,g,np.zeros_like(v))
        self.assertFalse(out[...,:3][v<=.12].any())
        self.assertLessEqual(abs(np.diff(out[0,:,0].astype(int))).max(),1)

    def test_invalid_display_weights_fail(self):
        with self.assertRaises(ValueError):
            context_pixels(np.zeros((1,1,4)),np.zeros((1,1,3)),np.array([[np.nan]]),np.zeros((1,1,3)),np.ones((1,1)))
