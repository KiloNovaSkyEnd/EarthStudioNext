import importlib.util
import json
import tempfile
from pathlib import Path
import unittest
import numpy as np
from scripts.prepare_ocean_reference import ocean_mask


class OceanMaskTests(unittest.TestCase):
    def test_ocean_mask_uses_geography_with_conservative_coast_margin(self):
        geometry={'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Polygon',
            'coordinates':[[[-10,-10],[10,-10],[10,10],[-10,10],[-10,-10]]]}}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'land.geojson';p.write_text(json.dumps(geometry))
            mask=ocean_mask(p,360)
        self.assertEqual(mask[90,180],0)   # supplied polygon inland
        self.assertEqual(mask[90,189],0)   # inside coast
        self.assertEqual(mask[90,191],0)   # coastal exclusion, outside polygon
        self.assertEqual(mask[90,210],255) # unambiguous water reference


@unittest.skipUnless(importlib.util.find_spec('moderngl'),'Optional GPU unavailable')
class TwilightRenderGPUTests(unittest.TestCase):
    def test_renderer_rebinds_its_own_textures_between_instances(self):
        from ges.atmosphere_scattering import ScatteringRenderer
        black=np.zeros((16,32,3),np.uint8)
        a=ScatteringRenderer([black]*3,65,65,cloud_layer=(np.full((16,32,4),[210,20,40,255],np.uint8),np.full((16,32),10,np.float32)))
        b=ScatteringRenderer([black]*3,65,65,cloud_layer=(np.full((16,32,4),[20,210,40,255],np.uint8),np.full((16,32),10,np.float32)))
        camera={'position':np.array([6971.,0,0]),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':30}
        try:
            for r,expected in [(a,[210,20,40]),(b,[20,210,40]),(a,[210,20,40])]:
                im=r.render(camera,[-1.,0,0],enabled=False)
                np.testing.assert_array_equal(im[32,32],expected)
        finally:b.close();a.close()

    def test_static_ocean_response_preserves_land_and_has_no_night_sun_glint(self):
        from ges.atmosphere_scattering import ScatteringRenderer
        old=np.full((16,32,3),80,np.uint8);day=np.full_like(old,30);night=np.zeros_like(old)
        camera={'position':np.array([6971.,0,0]),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':30}
        for mask_value in [0,255]:
            r=ScatteringRenderer([old,day,night],65,65,ocean_mask=np.full((16,32),mask_value,np.uint8))
            try:
                off=r.render(camera,[-1.,0,0],enabled=False,ocean_material=False)
                on=r.render(camera,[-1.,0,0],enabled=False,ocean_material=True)
                if mask_value==0:np.testing.assert_array_equal(off,on)
                else:self.assertEqual(on.max(),0)
            finally:r.close()

    def test_airglow_is_explicit_independent_switch_with_nonzero_night_limb(self):
        from ges.atmosphere_scattering import ScatteringRenderer
        black=np.zeros((16,32,3),np.uint8);r=ScatteringRenderer([black]*3,129,129)
        camera={'position':np.array([10000.,0,0]),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':60}
        try:
            off=r.render(camera,[-1.,0,0],enabled=False,airglow=False)
            on=r.render(camera,[-1.,0,0],enabled=False,airglow=True,steps=192)
            zero=r.render(camera,[-1.,0,0],enabled=False,airglow=True,gain=0,steps=192)
            self.assertEqual(off.max(),0);np.testing.assert_array_equal(off,zero)
            self.assertGreater(on.max(),5)
        finally:r.close()

    def test_cloud_colour_grid_can_be_finer_than_retrieved_height_grid(self):
        from ges.atmosphere_scattering import ScatteringRenderer
        ground=np.zeros((16,32,3),np.uint8);cloud=np.full((64,128,4),[100,150,200,255],np.uint8)
        r=ScatteringRenderer([ground]*3,65,65,cloud_layer=(cloud,np.full((16,32),10,np.float32)))
        camera={'position':np.array([6971.,0,0]),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':30}
        try:
            pixels=r.render(camera,[-1.,0,0],enabled=False,relief_strength=.4)
            np.testing.assert_array_equal(pixels[32,32],[100,150,200])
        finally:r.close()
