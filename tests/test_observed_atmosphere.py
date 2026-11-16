import unittest

import numpy as np

from ges.atmosphere_scattering import geographic,camera_basis,sphere_roots
from ges.catalog import utc_time
from ges.observed_atmosphere import ObservedAtmosphereRenderer,resolve_linear_samples
from ges.solar import sun_direction


class ObservedAtmosphereGPUTests(unittest.TestCase):
    def renderer(self,stamp,hole=False,night_color=(0,0,0)):
        r = ObservedAtmosphereRenderer(np.full((16,32,3),night_color,'uint8'),128,128,1.)
        projection = dict(proj='geos',a=6378137.,b=6356752.3,h=35785863.,lon_0=140.7,sweep='y')
        extent = [-5500000.,-5500000.,5500000.,5500000.]
        nav = dict(projection=projection,extent_m=extent,nominal_utc=stamp)
        obs = dict(projection=projection,area_extent_m=extent,nominal_utc=stamp,output_shape_yx=[256,256])
        r.update(np.zeros((256,256,4),'uint8'),np.full((128,128),np.nan,'float32'),nav)
        valid = np.ones((256,256),bool)
        if hole:
            valid[128,128] = False
        r.set_observation(np.full((256,256,3),.4,'float32'),valid,obs)
        return r

    def test_nadir_apparent_rgb_is_not_given_a_second_atmosphere(self):
        stamp = '2022-08-31T03:00:00Z'
        r = self.renderer(stamp)
        cam = dict(position=geographic(140.7,0,7071),target=geographic(140.7,0,6371),up=np.array([0.,0.,1.]),fov=20.)
        try:
            sun = sun_direction(utc_time(stamp))
            a = r.render(cam,sun,atmosphere=True,airglow=False,float_output=True)
            b = r.render(cam,sun,atmosphere=False,airglow=False,float_output=True)
            np.testing.assert_allclose(a[63:65,63:65],b[63:65,63:65],atol=1e-5)
            # Peripheral rays genuinely have a little extra slant column.
            self.assertLess(float(np.max(abs(a-b))),.5/255)
        finally:
            r.close()

    def test_night_airglow_is_present_outside_and_absent_over_opaque_ground(self):
        stamp = '2022-08-31T15:00:00Z'
        r = self.renderer(stamp,night_color=(40,60,80))
        cam = dict(position=geographic(140.7,0,24000),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=38.)
        right,up,forward = camera_basis(cam['position'],cam['target'],cam['up'])
        yy,xx = np.indices((128,128))
        ray = forward+np.tan(np.deg2rad(19))*((2*(xx+.5)-128)[...,None]/128*right+(128-2*(yy+.5))[...,None]/128*up)
        ray /= np.linalg.norm(ray,axis=-1,keepdims=True)
        ground = sphere_roots(cam['position'],ray,6371)[...,0] < np.inf
        from scipy.ndimage import binary_erosion
        opaque_interior=binary_erosion(ground,structure=np.ones((3,3),bool))
        try:
            sun = sun_direction(utc_time(stamp))
            a = r.render(cam,sun,atmosphere=False,airglow=True,float_output=True)
            b = r.render(cam,sun,atmosphere=False,airglow=False,float_output=True)
            # Central rays on the silhouette can share a pixel with sky rays.
            np.testing.assert_array_equal(a[opaque_interior],b[opaque_interior])
            self.assertGreater(float(np.max(a[~ground,:3]-b[~ground,:3])),1e-5)
            # False-colour IR must not acquire visible-band amber extinction.
            visible_atmosphere = r.render(cam,sun,atmosphere=True,airglow=False,float_output=True)
            # An illuminated upper path can add very faint twilight airlight;
            # it must never spectrally attenuate the false-colour IR base.
            self.assertTrue(((visible_atmosphere-b)[opaque_interior]>=-1e-6).all())
            self.assertLess(float(np.max(abs(visible_atmosphere-b)[opaque_interior])),.1/255)
        finally:
            r.close()

    def test_support_follows_actual_source_cell_instead_of_filtered_alpha(self):
        # Constant synthetic fixture tests filtering/coverage, not new weather.
        stamp = '2022-08-31T03:00:00Z'
        r = self.renderer(stamp,hole=True)
        cam = dict(position=geographic(140.7,0,7471),target=geographic(140.7,0,6371),up=np.array([0.,0.,1.]),fov=4.)
        try:
            sun = sun_direction(utc_time(stamp))
            uv = r.render(cam,sun,debug_projection=True,float_output=True)[...,:2]
            cell = np.floor(uv*256).astype(int)
            expected = ~((cell[...,0] == 128)&(cell[...,1] == 128))
            self.assertTrue((~expected).any())
            image = r.render(cam,sun,coverage_debug=True,atmosphere=False,airglow=False,float_output=True)
            green = (image[...,1] > .99)&(image[...,0] < .01)&(image[...,2] < .01)
            np.testing.assert_array_equal(green,expected)
        finally:
            r.close()

    def test_weight_debug_does_not_include_atmosphere_or_space_glow(self):
        stamp = '2022-08-31T03:00:00Z'
        r = self.renderer(stamp)
        cam = dict(position=geographic(140.7,0,24000),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=38.)
        try:
            sun = sun_direction(utc_time(stamp))
            a = r.render(cam,sun,weight_debug=True,float_output=True)
            b = r.render(cam,sun,weight_debug=True,atmosphere=False,airglow=False,float_output=True)
            np.testing.assert_array_equal(a,b)
            self.assertEqual(float(a[0,0,0]),0.)
        finally:
            r.close()

    def test_twilight_tangent_airlight_has_no_dark_interior_band(self):
        # Synthetic black IR/constant RGB isolate the geometric horizon. The
        # tiny FOV places adjacent rays immediately either side of tangency.
        stamp='2022-08-31T06:45:00Z'
        r=self.renderer(stamp)
        position=geographic(140.7,0.,7071.)
        tangent=np.rad2deg(np.arccos(6371./7071.))
        cam=dict(position=position,target=geographic(140.7+tangent,0.,6371.),
                 up=position/np.linalg.norm(position),fov=.05)
        try:
            sun=sun_direction(utc_time(stamp))
            uv=r.render(cam,sun,debug_projection=True,float_output=True)
            image=r.render(cam,sun,airglow=False,float_output=True)
            y=int(np.flatnonzero(uv[:,64,0]>=0)[0])
            self.assertGreater(y,0)
            above,below=image[y-1,64,:3],image[y,64,:3]
            self.assertGreater(float(above[2]),.1)
            self.assertGreater(float(below[2]),.1)
            self.assertLess(float(np.max(abs(above-below))),1./255)
        finally:
            r.close()

    def test_actual_ir_fallback_does_not_fill_vis_and_is_cleared_on_update(self):
        stamp='2022-08-31T03:00:00Z'
        r=self.renderer(stamp,hole=True)
        nav=r._cloud_metadata
        obs=dict(projection=nav['projection'],area_extent_m=nav['extent_m'],
                 nominal_utc=stamp,output_shape_yx=[256,256])
        position=geographic(140.7,0.,7471.)
        cam=dict(position=position,target=geographic(140.7,0.,6371.),up=np.array([0.,0.,1.]),fov=4.)
        valid=np.ones((256,256),bool);valid[128,128]=False
        rgb=np.full((256,256,3),.4,'float32')
        try:
            sun=sun_direction(utc_time(stamp))
            uv=r.render(cam,sun,debug_projection=True,float_output=True)[...,:2]
            cell=np.floor(uv*256).astype(int)
            hole=(cell[...,0]==128)&(cell[...,1]==128)
            before=r.render(cam,sun,atmosphere=False,airglow=False)
            r.set_ir_support(np.ones((256,256),bool),obs)
            fallback=r.render(cam,sun,atmosphere=False,airglow=False)
            np.testing.assert_array_equal(fallback[hole],0)
            coverage=r.render(cam,sun,coverage_debug=True,atmosphere=False,airglow=False)
            self.assertFalse((coverage[hole,1]>250).any())
            with self.assertRaisesRegex(ValueError,'UTC'):
                r.set_ir_support(np.ones((256,256),bool),{**obs,'nominal_utc':'2022-08-31T04:00:00Z'})
            r.update(np.zeros((256,256,4),'uint8'),np.full((128,128),np.nan,'float32'),nav)
            r.set_observation(rgb,valid,obs)
            stale_cleared=r.render(cam,sun,atmosphere=False,airglow=False)
            np.testing.assert_array_equal(stale_cleared,before)
        finally:
            r.close()

    def test_local_limb_sampling_matches_independent_sphere_pixel_coverage(self):
        stamp='2022-08-31T03:00:00Z'
        r=self.renderer(stamp)
        nav=r._cloud_metadata
        obs=dict(projection=nav['projection'],area_extent_m=nav['extent_m'],nominal_utc=stamp,output_shape_yx=[256,256])
        cam=dict(position=geographic(140.7,0.,24000.),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=38.)
        try:
            r.set_observation(np.ones((256,256,3),'float32'),np.ones((256,256),bool),obs)
            sun=sun_direction(utc_time(stamp))
            aa=r.render(cam,sun,atmosphere=False,airglow=False,clouds=False,float_output=True)
            with r.ctx:r.program['observed_limb_antialias'].value=False
            point=r.render(cam,sun,atmosphere=False,airglow=False,clouds=False,float_output=True)
            np.testing.assert_array_equal(aa[48:80,48:80],point[48:80,48:80])
            right,up,forward=camera_basis(cam['position'],cam['target'],cam['up'])
            offsets=(np.arange(32)+.5)/32-.5
            x=np.arange(128)[:,None,None]+.5+offsets[None,None,:]
            y=64.5+offsets[None,:,None]
            rays=forward+np.tan(np.deg2rad(19))*((2*x-128)[...,None]/128*right+(128-2*y)[...,None]/128*up)
            rays/=np.linalg.norm(rays,axis=-1,keepdims=True)
            coverage=np.isfinite(sphere_roots(cam['position'],rays,6371)[...,0]).mean((1,2))
            partial=(coverage>.05)&(coverage<.95)
            self.assertTrue(partial.any())
            def decode(encoded):
                return np.where(encoded<=.04045,encoded/12.92,((encoded+.055)/1.055)**2.4)
            aa_error=abs(decode(aa[64,:,0])-coverage)[partial]
            point_error=abs(decode(point[64,:,0])-coverage)[partial]
            self.assertLess(float(aa_error.max()),.14)
            self.assertLess(float(aa_error.mean()),float(point_error.mean()))
        finally:
            r.close()


class LinearResolveTests(unittest.TestCase):
    def test_black_white_boundary_averages_photons_instead_of_encoded_values(self):
        samples=np.zeros((2,2,4),'float32');samples[:,1,:3]=1.;samples[...,3]=1.
        image=resolve_linear_samples(samples,1,1)
        np.testing.assert_array_equal(image,np.full((1,1,3),188,'uint8'))

    def test_constant_colour_and_channel_bounds_are_preserved_without_ringing(self):
        samples=np.full((6,6,3),.4,'float32')
        np.testing.assert_array_equal(resolve_linear_samples(samples,2,2),np.full((2,2,3),102,'uint8'))
        samples[:,:3]=.2;samples[:,3:]=.8
        image=resolve_linear_samples(samples,3,3)
        self.assertGreaterEqual(int(image.min()),51)
        self.assertLessEqual(int(image.max()),204)


if __name__ == '__main__':
    unittest.main()
