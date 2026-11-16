import unittest
import numpy as np

from ges.atmosphere_scattering import geographic, orbit_camera, camera_basis
from ges.catalog import utc_time
from ges.presentation_earth import PresentationEarthRenderer, rim_weights
from ges.solar import sun_direction


class RimContractTests(unittest.TestCase):
    def test_attached_profiles_have_no_detached_peak_or_black_gap(self):
        h = np.array([-20., -1., 0., 1., 20., 90.])
        blue, _ = rim_weights(h, 1.)
        _, warm = rim_weights(h, -1.)
        self.assertEqual(int(blue.argmax()), 2)
        self.assertEqual(int(warm.argmax()), 2)
        self.assertTrue((warm[1:5] > 0).all())
        self.assertLess(warm[-1], warm[3]/1000)

    def test_solar_transition_is_continuous_and_has_exact_day_night_endpoints(self):
        mu = np.linspace(-.3, .3, 2001)
        b, w = rim_weights(0., mu)
        self.assertTrue(np.all(np.diff(b) >= -1e-12))
        self.assertTrue(np.all(np.diff(w) <= 1e-12))
        self.assertEqual(b[0], 0.)
        self.assertEqual(w[-1], 0.)
        self.assertLess(np.max(abs(np.diff(b))), .003)
        np.testing.assert_array_equal(rim_weights(0., mu, warm=False)[1], np.zeros_like(mu))


class FlatEarthGPUTests(unittest.TestCase):
    def make(self, stamp, width=192, height=128):
        r = PresentationEarthRenderer(np.zeros((8,16,3),'uint8'), width, height, 1)
        pr = dict(proj='geos', a=6378137., b=6356752.3, h=35785863., lon_0=140.7, sweep='y')
        extent = [-5500000., -5500000., 5500000., 5500000.]
        nav = dict(projection=pr, extent_m=extent, nominal_utc=stamp)
        obs = dict(projection=pr, area_extent_m=extent, nominal_utc=stamp, output_shape_yx=[256,256], source_fade_applied=False)
        yy, xx = np.indices((256,256))
        rgba = np.full((256,256,4),255,'uint8')
        rgba[...,0] = np.where(xx < 128,100,220)
        rgba[...,1] = np.where(xx < 128,150,220)
        rgba[...,2] = 220
        rgba[...,3] = np.where((xx+yy)%16 < 8,190,240)
        r.update(rgba, np.zeros((256,256),'float32'), nav)
        r.set_observation(np.full((256,256,3),.4,'float32'), np.ones((256,256),bool), obs)
        r.set_ir_support(np.ones((256,256),bool), obs)
        return r, rgba, nav, obs

    def test_cloud_height_thickness_and_volume_do_not_change_pixels(self):
        stamp = '2026-10-20T19:20:00Z'
        r, rgba, nav, obs = self.make(stamp)
        sun = sun_direction(utc_time(stamp))
        cam = orbit_camera(131,17,800,32)
        try:
            a = r.render(cam,sun,atmosphere=False,airglow=False,height_scale=.5,thickness=1.5,volume=True)
            r.update(rgba, np.full((256,256),20.,'float32'), nav)
            r.set_observation(np.full((256,256,3),.4,'float32'),np.ones((256,256),bool),obs)
            r.set_ir_support(np.ones((256,256),bool),obs)
            b = r.render(cam,sun,atmosphere=False,airglow=False,height_scale=0.,thickness=.2,volume=False)
            np.testing.assert_array_equal(a,b)
        finally: r.close()

    def test_day_rim_is_blue_and_cannot_produce_brown_extinction(self):
        stamp = '2026-10-20T03:00:00Z'
        r, _, _, _ = self.make(stamp)
        cam = dict(position=geographic(140.7,0,42164),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=21.)
        try:
            image = r.render(cam,sun_direction(utc_time(stamp)),airglow=False)
            right, up, forward = camera_basis(cam['position'],cam['target'],cam['up'])
            yy,xx=np.indices((128,192))
            rays=forward+np.tan(np.deg2rad(10.5))*((2*(xx+.5)-192)[...,None]/128*right+(128-2*(yy+.5))[...,None]/128*up)
            rays/=np.linalg.norm(rays,axis=-1,keepdims=True)
            h=np.linalg.norm(np.cross(cam['position'],rays),axis=-1)-6371
            rim=(h>=0)&(h<100)&(image[...,2]>3)
            self.assertGreater(int(rim.sum()),10)
            self.assertTrue((image[...,2][rim]>=image[...,1][rim]).all())
            self.assertTrue((image[...,1][rim]>=image[...,0][rim]).all())
        finally:r.close()

    def test_attached_night_glow_reaches_the_silhouette(self):
        stamp = '2026-10-20T19:20:00Z'
        r,_,_,_=self.make(stamp)
        cam=orbit_camera(131,17,800,32)
        try:
            sun=sun_direction(utc_time(stamp))
            on=r.render(cam,sun,atmosphere=False,airglow=True)
            off=r.render(cam,sun,atmosphere=False,airglow=False)
            right,up,forward=camera_basis(cam['position'],cam['target'],cam['up'])
            yy,xx=np.indices((128,192))
            rays=forward+np.tan(np.deg2rad(16))*((2*(xx+.5)-192)[...,None]/128*right+(128-2*(yy+.5))[...,None]/128*up)
            rays/=np.linalg.norm(rays,axis=-1,keepdims=True)
            h=np.linalg.norm(np.cross(cam['position'],rays),axis=-1)-6371
            near=(h>0)&(h<12)
            self.assertGreater(int(near.sum()),0)
            self.assertGreater(float(np.mean(on[...,0][near]-off[...,0][near])),1.)
        finally:r.close()

    def test_blue_only_rim_disappears_at_night_and_returns_with_sun(self):
        r, rgba, nav, obs = self.make('2026-10-20T03:00:00Z')
        cam = orbit_camera(131,17,800,32)
        def bind_time(stamp):
            # Synthetic fixture with matched UTC throughout; production still
            # rejects changing the Sun while retaining another scan's UTC.
            nav['nominal_utc'] = obs['nominal_utc'] = stamp
            r.update(rgba,None,nav)
            r.set_observation(np.full((256,256,3),.4,'float32'),np.ones((256,256),bool),obs)
            r.set_ir_support(np.ones((256,256),bool),obs)
            return sun_direction(utc_time(stamp))
        try:
            day = r.render(cam,bind_time('2026-10-20T03:00:00Z'),airglow=False)
            sun = bind_time('2026-10-20T19:20:00Z')
            night = r.render(cam,sun,airglow=False)
            night_without_rim = r.render(cam,sun,airglow=False,atmosphere=False)
            returned = r.render(cam,bind_time('2026-10-20T03:00:00Z'),airglow=False)
            np.testing.assert_array_equal(night,night_without_rim)
            np.testing.assert_array_equal(day,returned)
            self.assertTrue(np.any(day[...,2] > night[...,2]))
        finally:r.close()
