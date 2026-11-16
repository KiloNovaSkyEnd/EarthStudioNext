import unittest
import numpy as np
from ges.film_transition import vis_cloud_alpha,layered_pixels,smoother,daylight_display


class FilmTransitionTests(unittest.TestCase):
    def test_sunlit_profile_preserves_support_texture_and_white(self):
        a=np.linspace(0,1,1001,dtype=np.float32)
        ground=np.tile(np.arange(256,dtype=np.uint8)[:,None],(1,3))
        lifted,linear=daylight_display(a,ground,'sunlit-v1')
        self.assertEqual(lifted[0],0);self.assertEqual(lifted[-1],1)
        self.assertTrue((np.diff(lifted)>0).all())
        self.assertTrue((np.diff(linear[:,0])>0).all())
        self.assertEqual(linear[0,0],0);self.assertAlmostEqual(float(linear[-1,0]),1,places=6)
        from ges.blend_night import encode_rgb
        self.assertGreater(int(encode_rgb(linear)[120,0]),145)

    def test_sunlit_day_brighter_with_exact_night_and_unchanged_weights(self):
        n=np.tile(np.array([140,191,250,150],np.uint8),(1,5,1));g=np.full((1,5,3),100,np.uint8)
        args=(np.full((1,5),.35),np.ones((1,5),bool),n,np.ones((1,5),bool),g,np.full_like(g,10),np.array([[-20,-12,-11.999,25,50]]))
        old,*oldweights=layered_pixels(*args)
        new,*weights=layered_pixels(*args,daylight_profile='sunlit-v1')
        np.testing.assert_array_equal(old[:,:2],new[:,:2])
        for x,y in zip(oldweights,weights):np.testing.assert_array_equal(x,y)
        self.assertGreater(int(new[0,3,0]),int(old[0,3,0])+20)
        self.assertLessEqual(abs(new[0,2,:3].astype(int)-new[0,1,:3]).max(),1)
        missing,*_=layered_pixels(*args[:1],np.zeros((1,5),bool),n,np.zeros((1,5),bool),g,g,args[-1],daylight_profile='sunlit-v1')
        self.assertFalse(missing.any())

    def test_deep_night_boundary_has_no_compositing_space_jump(self):
        n=np.tile(np.array([140,191,250,150],np.uint8),(1,3,1));g=np.full((1,3,3),120,np.uint8)
        out,*_=layered_pixels(np.full((1,3),.8),np.ones((1,3),bool),n,np.ones((1,3),bool),g,np.full_like(g,20),np.array([[-12.001,-12,-11.999]]))
        self.assertLessEqual(abs(np.diff(out[0,:,:3].astype(int),axis=0)).max(),1)

    def test_reference_ground_has_no_dependency_on_visible_coverage(self):
        n=np.zeros((1,2,4),np.uint8);g=np.full((1,2,3),120,np.uint8)
        out,cw,iw,sw=layered_pixels(np.zeros((1,2)),np.array([[True,False]]),n,np.ones((1,2),bool),g,np.full_like(g,10),np.array([[10,10]]))
        np.testing.assert_array_equal(out[0,0],out[0,1]);self.assertEqual(sw[0,0],sw[0,1])

    def test_solar_curve_has_no_endpoint_slope_or_curvature_jump(self):
        x=np.linspace(-15,27,42001);y=smoother(x,0,24)
        self.assertTrue((np.diff(y)>=-1e-12).all());self.assertLess(abs(np.diff(y)).max(),.00008)
        self.assertLess(abs(smoother(.001,0,24)-smoother(0,0,24)),1e-10)
        self.assertLess(abs(smoother(24,0,24)-smoother(23.999,0,24)),1e-10)

    def test_cloud_labels_and_invalid_vis_are_not_expanded(self):
        a,cov=vis_cloud_alpha(np.array([[.5,.5,np.nan,.5]]),np.array([[1,3,9,4]]),30,30)
        self.assertEqual(a[0,0],0);self.assertGreater(a[0,1],0)
        np.testing.assert_array_equal(cov,[[True,True,False,False]]);self.assertFalse(a[0,2:].any())

    def test_vis_cannot_leak_past_either_scan_endpoint_horizon(self):
        a,cov=vis_cloud_alpha(np.array([[.5,.5]]),np.array([[9,3]]),np.array([[-1,1]]),np.array([[1,-1]]))
        self.assertFalse(a.any());self.assertFalse(cov.any())

    def test_static_ground_never_creates_missing_cloud_coverage(self):
        n=np.zeros((1,1,4),np.uint8);g=np.full((1,1,3),255,np.uint8)
        out,*_=layered_pixels(np.zeros((1,1)),np.zeros((1,1),bool),n,np.zeros((1,1),bool),g,g,10)
        self.assertFalse(out.any())

    def test_deep_night_rgb_exact_and_sunlit_cloud_is_not_blue(self):
        n=np.array([[[140,191,250,150],[140,191,250,150]]],np.uint8);g=np.full((1,2,3),20,np.uint8)
        out,cw,iw,sw=layered_pixels(np.full((1,2),.8),np.ones((1,2),bool),n,np.ones((1,2),bool),g,g,np.array([[-20,40]]))
        expected=np.rint(n[0,0,:3]*(150/255)+20*(1-150/255)).astype(np.uint8)
        np.testing.assert_array_equal(out[0,0,:3],expected)
        self.assertEqual(out[0,1,0],out[0,1,2]);self.assertEqual(cw[0,0],0);self.assertEqual(iw[0,1],0)

    def test_cloud_alpha_keeps_bright_measurement_texture(self):
        a,cov=vis_cloud_alpha(np.array([[.8,.9,1.,1.1]]),np.full((1,4),3),90,90)
        self.assertTrue((np.diff(a)>0).all());self.assertTrue(cov.all())


if __name__=='__main__':unittest.main()
