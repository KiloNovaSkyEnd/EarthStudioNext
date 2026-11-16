"""Synthetic sampling fixtures only; not satellite observations."""
import unittest
import numpy as np
from ges.atmosphere_scattering import geographic
from ges.goni_film import NativeCloudRenderer
from tests.test_native_ocean import META


class NightDetailTests(unittest.TestCase):
    def setUp(self):
        day=np.zeros((16,32,3),np.uint8)
        self.r=NativeCloudRenderer(day,np.full_like(day,40),65,65,1)
        self.r.update(np.zeros((64,96,4),np.uint8),np.full((32,48),np.nan,np.float32),META)

    def tearDown(self):self.r.close()

    def render(self,lon=130,lat=35,**over):
        p=geographic(lon,lat,7971)
        cam=dict(position=p,target=geographic(lon,lat,6371),up=np.array([0.,0.,1.]),fov=10)
        return self.r.render(cam,-p/np.linalg.norm(p),**dict(atmosphere=False,airglow=False,clouds=False,city_light_gain=1.,**over))

    def test_disabled_and_removed_detail_preserve_default_exactly(self):
        old=self.render()
        self.r.set_night_detail(np.full((128,192,3),80,np.uint8),(100,15,160,55))
        new=self.render()
        self.assertGreater(int(new[32,32,0]),int(old[32,32,0]))
        self.r.set_night_detail()
        np.testing.assert_array_equal(old,self.render())

    def test_north_first_uv_and_nonadditive_emissive(self):
        a=np.zeros((256,256,3),np.uint8)
        a[:,:,0]=np.arange(256)[None,:];a[:,:,1]=np.arange(256)[:,None];a[:,:,2]=80
        self.r.set_night_detail(a,(100,15,160,55))
        c=self.render()[32,32]
        np.testing.assert_allclose(c,[127.5,127.5,80],atol=1)
        c=self.render(lon=115,lat=45)[32,32]
        np.testing.assert_allclose(c,[63.5,63.5,80],atol=1)

    def test_outside_region_falls_back_and_lights_off_remains_exact(self):
        before=self.render(lon=70)
        off=self.render(city_lights=False)
        self.r.set_night_detail(np.full((128,192,3),180,np.uint8),(100,15,160,55))
        np.testing.assert_array_equal(before,self.render(lon=70))
        np.testing.assert_array_equal(off,self.render(city_lights=False))

    def test_invalid_grid_and_bounds_are_rejected_before_replacing(self):
        a=np.zeros((16,32,3),np.uint8)
        for grid,bounds in [(a.astype(float),(100,15,160,55)),(a,(170,15,-170,55)),
                            (a,(100,15,160,float('nan'))),(a,None),(a,(100,15,101,55))]:
            with self.assertRaises(ValueError):self.r.set_night_detail(grid,bounds)

    def test_daylight_and_overlay_outer_boundary_remain_global(self):
        p=geographic(130,35,7971)
        cam=dict(position=p,target=geographic(130,35,6371),up=np.array([0.,0.,1.]),fov=10)
        sun=p/np.linalg.norm(p)
        before=self.r.render(cam,sun,clouds=False)
        self.r.set_night_detail(np.full((128,192,3),180,np.uint8),(100,15,160,55))
        np.testing.assert_array_equal(before,self.r.render(cam,sun,clouds=False))
        # An interior-only join must reach the unchanged global sample at the edge.
        np.testing.assert_allclose(self.render(lon=100)[32,32],[40,40,40],atol=1)
