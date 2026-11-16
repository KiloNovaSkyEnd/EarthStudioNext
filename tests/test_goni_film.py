import importlib.util
import unittest
import numpy as np
from pyproj import Transformer
from ges.goni_film import native_project
from ges.atmosphere_scattering import geographic

PROJECTION=dict(proj='geos',a=6378137.,b=6356752.3,h=35785863.,lon_0=140.7,sweep='y')
META={'projection':PROJECTION,'extent_m':[-4100000.,-1100000.,3300000.,4300000.]}


class NativeNavigationTests(unittest.TestCase):
    def test_analytic_native_mapping_matches_independent_proj(self):
        lo,la=np.meshgrid(np.linspace(100,175,17),np.linspace(-5,50,13))
        expected=Transformer.from_crs('EPSG:4326',PROJECTION,always_xy=True).transform(lo,la)
        actual=native_project(lo,la,PROJECTION)
        for a,b in zip(actual,expected):np.testing.assert_allclose(a,b,atol=.00001)


@unittest.skipUnless(importlib.util.find_spec('moderngl'),'Optional GPU unavailable')
class NativeVolumeTests(unittest.TestCase):
    def test_display_geometry_interpolation_does_not_fill_measured_height_nan(self):
        from ges.goni_film import NativeCloudRenderer
        black=np.zeros((16,32,3),np.uint8);r=NativeCloudRenderer(black,black,65,65,1,opacity_gamma=1.25,geometry_bridge_pixels=2)
        h=np.full((32,48),14,np.float32);h[15:17,23:25]=np.nan;original=h.copy()
        cloud=np.full((64,96,4),[220,220,220,153],np.uint8);original_cloud=cloud.copy()
        try:
            r.update(cloud,h,META)
            np.testing.assert_array_equal(h,original);np.testing.assert_array_equal(cloud,original_cloud)
            self.assertGreater(r.geometry_interpolated_cells,0)
        finally:r.close()

    def test_airglow_independent_toggle_emits_only_when_enabled(self):
        r,camera=self.renderer(alpha=0)
        camera={'position':geographic(140.7,15,20000),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':45}
        try:
            sun=-camera['position']/np.linalg.norm(camera['position'])
            off=r.render(camera,sun,atmosphere=False,airglow=False)
            on=r.render(camera,sun,atmosphere=False,airglow=True)
            self.assertEqual(int(off.max()),0);self.assertGreater(int(on.max()),0)
        finally:r.close()

    def renderer(self,alpha=153):
        from ges.goni_film import NativeCloudRenderer
        black=np.zeros((16,32,3),np.uint8);r=NativeCloudRenderer(black,black,65,65,1)
        r.update(np.full((64,96,4),[220,220,220,alpha],np.uint8),np.full((32,48),14,np.float32),META)
        camera={'position':geographic(140.7,15,6971),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':30}
        return r,camera

    def test_gpu_native_uv_matches_proj_at_real_geographic_targets(self):
        r,camera=self.renderer()
        try:
            for lo,la in [(140.7,15),(120,30),(160,5)]:
                camera['position']=geographic(lo,la,6971)
                pixels=r.render(camera,[1.,0,0],debug_projection=True,float_output=True)
                x,y=native_project(lo,la,PROJECTION);xmin,ymin,xmax,ymax=META['extent_m']
                # Float GPU trigonometry must stay within1/4 of a native2km
                # IR pixel; CPU reference above is checked to10micrometres.
                error=abs(pixels[32,32,:2]-np.array([(x-xmin)/(xmax-xmin),(ymax-y)/(ymax-ymin)]))*[xmax-xmin,ymax-ymin]
                self.assertLess(float(error.max()),500.)
        finally:r.close()

    def test_vertical_volume_integral_matches_independent_beer_lambert(self):
        r,camera=self.renderer()
        try:
            sun=-camera['position']/np.linalg.norm(camera['position'])
            image=r.render(camera,sun,atmosphere=False,airglow=False,volume_samples=192)
            linear=((220/255+.055)/1.055)**2.4*(153/255)*np.array([.82,.89,1.])
            expected=(1.055*linear**(1/2.4)-.055)*255
            np.testing.assert_allclose(image[32,32],expected,atol=4)
            np.testing.assert_array_equal(image,r.render(camera,sun,atmosphere=False,airglow=False,volume_samples=192))
        finally:r.close()

    def test_no_glint_or_cloud_can_appear_in_empty_observations(self):
        r,camera=self.renderer(alpha=0)
        try:
            image=r.render(camera,camera['position']/np.linalg.norm(camera['position']),atmosphere=False,airglow=False)
            self.assertEqual(int(image.max()),0)
        finally:r.close()

    def test_thin_unsupported_shell_survives_coarse_segment_sampling(self):
        r,camera=self.renderer()
        try:
            r.update(np.full((64,96,4),[220,220,220,153],np.uint8),np.full((32,48),np.nan,np.float32),META)
            sun=-camera['position']/np.linalg.norm(camera['position'])
            coarse=r.render(camera,sun,atmosphere=False,airglow=False,volume_samples=32)
            fine=r.render(camera,sun,atmosphere=False,airglow=False,volume_samples=192)
            np.testing.assert_allclose(coarse[32,32].astype(float),fine[32,32],atol=3)
            self.assertGreater(int(coarse[32,32].min()),100)
        finally:r.close()

    def test_water_changes_with_sun_without_saturated_disk(self):
        from ges.goni_film import NativeCloudRenderer
        day=np.full((16,32,3),[15,32,50],np.uint8);black=np.zeros_like(day)
        r=NativeCloudRenderer(day,black,65,65,1,ocean_mask=np.full((16,32),255,np.uint8))
        try:
            r.update(np.zeros((64,96,4),np.uint8),np.full((32,48),np.nan,np.float32),META)
            camera={'position':geographic(140.7,15,9371),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':30}
            sun=camera['position']/np.linalg.norm(camera['position'])
            lit=r.render(camera,sun,atmosphere=False,airglow=False)
            dark=r.render(camera,-sun,atmosphere=False,airglow=False)
            self.assertGreater(float(lit.mean()-dark.mean()),5)
            self.assertLess(int(lit.max()),100);self.assertLess(int(dark.max()),5)
        finally:r.close()
