import importlib.util
import unittest
import numpy as np
from ges.atmosphere_scattering import geographic
from ges.goni_film import NativeCloudRenderer

META={'projection':dict(proj='geos',a=6378137.,b=6356752.3,h=35785863.,lon_0=140.7,sweep='y'),
      'extent_m':[-4100000.,-1100000.,3300000.,4300000.]}


@unittest.skipUnless(importlib.util.find_spec('moderngl'),'Optional GPU unavailable')
class NativeOceanControlsTests(unittest.TestCase):
    def renderer(self,water):
        day=np.full((16,32,3),[2,5,20],np.uint8);night=np.full_like(day,30)
        r=NativeCloudRenderer(day,night,65,65,1,ocean_mask=np.full((16,32),water,np.uint8))
        r.update(np.zeros((64,96,4),np.uint8),np.full((32,48),np.nan,np.float32),META)
        camera={'position':geographic(140.7,15,6971),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':30}
        return r,camera

    def test_candidate_is_water_only_and_legacy_remains_default(self):
        for water in [0,255]:
            r,camera=self.renderer(water)
            try:
                sun=camera['position']/np.linalg.norm(camera['position'])
                settings=dict(atmosphere=False,airglow=False,ocean_reflections=False,clouds=False)
                old=r.render(camera,sun,**settings)
                np.testing.assert_array_equal(old,r.render(camera,sun,deep_ocean_material=False,**settings))
                new=r.render(camera,sun,deep_ocean_material=True,**settings)
                if water==0:np.testing.assert_array_equal(new,old)
                else:
                    self.assertGreater(new[32,32,2],new[32,32,1]);self.assertGreater(int(new[32,32,2]),int(old[32,32,2]))
            finally:r.close()

    def test_lights_toggle_is_independent_of_ocean_and_exposure_is_bounded(self):
        r,camera=self.renderer(0)
        try:
            sun=-camera['position']/np.linalg.norm(camera['position'])
            settings=dict(atmosphere=False,airglow=False,clouds=False)
            on=r.render(camera,sun,**settings);off=r.render(camera,sun,city_lights=False,**settings)
            self.assertGreater(int(on.max()),int(off.max()))
            for value in [0,2.1,np.nan]:
                with self.assertRaises(ValueError):r.render(camera,sun,exposure=value)
            np.testing.assert_array_equal(on,r.render(camera,sun,exposure=1.,**settings))
            dim=r.render(camera,sun,city_light_gain=1.,**settings)
            self.assertLess(int(dim.max()),int(on.max()))
            for value in [0,2.1,np.nan]:
                with self.assertRaises(ValueError):r.render(camera,sun,city_light_gain=value)
        finally:r.close()

    def test_cloud_toggle_does_not_change_uploaded_observations(self):
        r,camera=self.renderer(255)
        try:
            rgba=np.full((64,96,4),[220,220,220,200],np.uint8);h=np.full((32,48),10,np.float32)
            original=rgba.copy();r.update(rgba,h,META)
            sun=camera['position']/np.linalg.norm(camera['position'])
            on=r.render(camera,sun,atmosphere=False,airglow=False)
            off=r.render(camera,sun,atmosphere=False,airglow=False,clouds=False)
            self.assertGreater(int(np.abs(on.astype(int)-off).max()),0)
            # OFF must remove both visible columns and their surface shadows.
            r.update(np.zeros_like(rgba),h,META)
            clear=r.render(camera,sun,atmosphere=False,airglow=False,clouds=False)
            np.testing.assert_array_equal(clear,off)
            np.testing.assert_array_equal(rgba,original)
        finally:r.close()
