import unittest
import numpy as np
from ges.blend_night import mix_pixels,grazing_alpha


class NightBlendTests(unittest.TestCase):
    def test_grazing_display_guard_keeps_rgb_and_central_alpha(self):
        p=np.tile(np.array([140,191,250,200],dtype=np.uint8),(1,4,1))
        g={'longitude':0,'latitude':0,'earth_radius_m':6378137,'altitude_m':35785863}
        out=grazing_alpha(p,np.array([[0,60,70,80]]),0,g)
        np.testing.assert_array_equal(out[...,:3],p[...,:3]);self.assertEqual(out[0,0,3],200)
        self.assertEqual(out[0,1,3],200);self.assertTrue(0<out[0,2,3]<200);self.assertEqual(out[0,3,3],0)
        np.testing.assert_array_equal(p[...,3],np.full((1,4),200))

    def test_transparent_source_does_not_pollute_color(self):
        a=np.array([[[255,0,0,255]]],dtype=np.uint8);b=np.array([[[0,0,255,0]]],dtype=np.uint8)
        out=mix_pixels([a,b],[np.ones((1,1)),np.ones((1,1))])
        np.testing.assert_array_equal(out[0,0],[255,0,0,128])

    def test_linear_light_mix_and_missing_coverage(self):
        a=np.array([[[255,0,0,255],[255,255,255,255]]],dtype=np.uint8)
        b=np.array([[[0,0,255,255],[0,0,0,255]]],dtype=np.uint8)
        out=mix_pixels([a,b],[np.array([[1,0]]),np.array([[1,0]])])
        np.testing.assert_array_equal(out[0,0],[188,0,188,255])
        np.testing.assert_array_equal(out[0,1],[0,0,0,0])

    def test_invalid_weights_rejected(self):
        with self.assertRaises(ValueError):mix_pixels([np.zeros((1,1,4),dtype=np.uint8)],[np.full((1,1),np.nan)])
