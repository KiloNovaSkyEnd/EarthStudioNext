import importlib.util
import unittest
import numpy as np
from ges.atmosphere_scattering import sphere_roots,solar_visibility,orbit_camera,camera_basis


class AtmosphereGeometryTests(unittest.TestCase):
    def test_outside_and_inside_atmosphere_intersections(self):
        np.testing.assert_allclose(sphere_roots([0,0,7000],[0,0,-1],6471),[529,13471])
        roots=sphere_roots([0,0,6451],[0,0,-1],6471)
        self.assertLess(roots[0],0);self.assertGreater(roots[1],0)
        self.assertTrue(np.isinf(sphere_roots([7000,0,0],[0,0,1],6471)).all())

    def test_earth_shadow_and_elevated_twilight_are_distinct(self):
        sun=np.array([1.,0,0]);angle=np.deg2rad(93.)
        direction=np.array([np.cos(angle),np.sin(angle),0])
        self.assertEqual(float(solar_visibility(direction*6371,sun)),0)
        self.assertEqual(float(solar_visibility(direction*6451,sun)),1)
        self.assertEqual(float(solar_visibility([-6451,0,0],sun)),0)

    def test_camera_basis_has_no_date_line_flip(self):
        bases=[]
        for lon in [179.999,-179.999]:
            camera=orbit_camera(lon,15,80)
            basis=np.array(camera_basis(camera['position'],camera['target'],camera['up']))
            np.testing.assert_allclose(basis@basis.T,np.eye(3),atol=1e-12);bases.append(basis)
        self.assertLess(abs(bases[0]-bases[1]).max(),.0001)
        with self.assertRaises(ValueError):orbit_camera(0,0,0)


@unittest.skipUnless(importlib.util.find_spec('moderngl'),'Optional GPU renderer unavailable')
class AtmosphereGPUPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ges.atmosphere_scattering import ScatteringRenderer
        fixture=np.full((16,32,3),128,np.uint8)
        try:cls.renderer=ScatteringRenderer([fixture]*3,65,65)
        except Exception as error:raise unittest.SkipTest('OpenGL context unavailable: '+str(error))

    @classmethod
    def tearDownClass(cls):cls.renderer.close()

    def test_nadir_transmittance_matches_independent_density_integrals(self):
        # No scattered/emitted light: Beer-Lambert can be independently solved
        # from exponential column densities and triangular ozone area15km.
        camera={'position':np.array([0.,0.,6771.]),'target':np.zeros(3),'up':np.array([0.,1.,0.]),'fov':5}
        image=self.renderer.render(camera,np.array([0.,0.,1.]),steps=192,sun_steps=4,exposure=0)
        tau=np.array([.005802,.013558,.0331])*8*(1-np.exp(-100/8))
        tau+=.00444*1.2*(1-np.exp(-100/1.2))+np.array([.00065,.001881,.000085])*15
        base=((128/255+.055)/1.055)**2.4
        expected=base*np.exp(-tau)
        expected=np.rint(np.where(expected<=.0031308,12.92*expected,1.055*expected**(1/2.4)-.055)*255)
        self.assertLessEqual(abs(image[32,32].astype(float)-expected).max(),1)

    def test_effect_off_keeps_original_texture_and_ignores_sun(self):
        camera=orbit_camera(-75,15,400)
        a=self.renderer.render(camera,np.array([1.,0.,0.]),enabled=False)
        b=self.renderer.render(camera,np.array([-1.,0.,0.]),enabled=False)
        np.testing.assert_array_equal(a,b)
        self.assertTrue(((a==0)|(a==128)).all())
