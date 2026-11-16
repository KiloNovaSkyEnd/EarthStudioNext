import importlib.util
import unittest
import numpy as np
from ges.cloud_relief import screened_height, height_display, separate_material


class CloudReliefTests(unittest.TestCase):
    def test_native_netcdf_height_mapping_and_time_guards(self):
        import tempfile
        from pathlib import Path
        import netCDF4
        from ges.cloud_relief import load_abi_height
        with tempfile.TemporaryDirectory() as folder:
            files=[]
            for kind in ['ACHAF','ACMF']:
                path=Path(folder)/f'ABI-L2-{kind}-fixture.nc';files.append(path)
                with netCDF4.Dataset(path,'w') as d:
                    d.platform_ID='G16';d.time_coverage_start='2020-10-29T16:40:00Z';d.time_coverage_end='2020-10-29T16:49:00Z'
                    d.createDimension('x',4);d.createDimension('y',4)
                    for name,values in [('x',np.linspace(-.15,.15,4)),('y',np.linspace(.15,-.15,4))]:
                        a=d.createVariable(name,'f8',(name,));a[:]=values;a.units='rad'
                    p=d.createVariable('goes_imager_projection','i4')
                    for key,value in dict(perspective_point_height=35786023.,semi_major_axis=6378137.,semi_minor_axis=6356752.31414,
                                          longitude_of_projection_origin=-75.,latitude_of_projection_origin=0.,sweep_angle_axis='x').items():
                        p.setncattr(key,value)
                    q=d.createVariable('DQF','i1',('y','x'));q[:]=0;q.flag_meanings='good_quality_qf bad_quality_qf'
                    field=d.createVariable('HT' if kind=='ACHAF' else 'BCM','f4',('y','x'),fill_value=-999)
                    field[:]=10000 if kind=='ACHAF' else 1
                    if kind=='ACHAF':field.units='m';field[1,1]=-999
            height,audit=load_abi_height(files,512,'goes16','2020-10-29T16:40:00Z','2020-10-29T16:49:00Z')
            self.assertGreater(np.isfinite(height).sum(),0)
            self.assertTrue(np.isnan(height).any())
            np.testing.assert_array_equal(height[np.isfinite(height)],10)
            self.assertEqual(audit['sources'][0]['native_shape'],[4,4])
            with self.assertRaisesRegex(ValueError,'same scan'):
                load_abi_height(files,512,'goes16','2020-10-29T16:50:00Z','2020-10-29T16:59:00Z')
            with self.assertRaisesRegex(ValueError,'platform'):
                load_abi_height(files,512,'goes17','2020-10-29T16:40:00Z','2020-10-29T16:49:00Z')

    def test_quality_and_cloud_mask_exclude_clear_bad_and_missing_heights(self):
        h = screened_height([12000, 3000, 9000, np.nan, -20, 25000],
                            [0, 1, 0, 0, 0, 0], [1, 1, 0, 1, 1, 1], [0]*6)
        self.assertEqual(h[0], 12)
        self.assertTrue(np.isnan(h[1:]).all())
        np.testing.assert_allclose(height_display(h), [4.5, .3, .3, .3, .3, .3])
        for value in [-1, .51, np.nan]:
            with self.assertRaises(ValueError): height_display(h, value)

    def test_ground_and_unknown_classes_cannot_become_cloud_geometry(self):
        night = np.array([[[50, 90, 180, 100]]*4], np.uint8)
        cloud = separate_material(np.array([[.02, .5, .8, .9]]), True, night,
                                  [[8, 1, 4, 0]], np.ones((1, 4)))
        self.assertEqual(int(cloud[0, 0, 3]), 5)  # weak measured low cloud retained
        self.assertTrue((cloud[0, 1:] == 0).all())
        deep = separate_material(np.zeros((1,4)), False, night, [[8]*4], np.zeros((1,4)))
        np.testing.assert_array_equal(deep, night)


@unittest.skipUnless(importlib.util.find_spec('moderngl'), 'Optional GPU unavailable')
class CloudReliefGPUTests(unittest.TestCase):
    def test_night_depth_twilight_gate_has_no_solar_cutoff_jump(self):
        cloud=np.full((128,256,4),[170,180,200,210],np.uint8)
        y,x=np.indices((128,256));heights=(8+5*np.sin(x*.3)*np.cos(y*.3)).astype(np.float32)
        renderer,camera=self.render_layer(cloud,heights)
        try:
            for boundary in [-6.,0.,6.]:
                frames=[]
                for elevation in [boundary-.001,boundary+.001]:
                    e=np.deg2rad(elevation)
                    frames.append(renderer.render(camera,[np.sin(e),np.cos(e),0.],enabled=False,
                        relief_strength=.4,night_depth_strength=1,float_output=True))
                self.assertLess(abs(frames[1]-frames[0]).max()*255,.2)
        finally:renderer.close()

    def test_night_depth_changes_only_supported_night_relief_and_keeps_day_exact(self):
        cloud=np.full((128,256,4),[170,180,200,210],np.uint8)
        y,x=np.indices((128,256));heights=(8+5*np.sin(x*.3)*np.cos(y*.3)).astype(np.float32)
        renderer,camera=self.render_layer(cloud,heights)
        try:
            def draw(sun,depth):
                return renderer.render(camera,sun,enabled=False,relief_strength=.4,night_depth_strength=depth)
            np.testing.assert_array_equal(draw([1.,0.,0.],0),draw([1.,0.,0.],1))
            a,b=draw([-1.,0.,0.],0),draw([-1.,0.,0.],1)
            self.assertGreater(np.count_nonzero(a!=b),100)
            self.assertLessEqual(abs(a.astype(float)-b.astype(float)).max(),20)
            np.testing.assert_array_equal(b,draw([-1.,0.,0.],1))
            for invalid in [-1,1.01,np.nan]:
                with self.assertRaises(ValueError):draw([-1.,0.,0.],invalid)
        finally:renderer.close()

    def render_layer(self, cloud, heights):
        from ges.atmosphere_scattering import ScatteringRenderer
        ground = np.full((32,64,3), 80, np.uint8)
        renderer = ScatteringRenderer([ground]*3, 65,65,cloud_layer=(cloud, heights))
        camera = {'position': np.array([6971.,0,0]), 'target': np.zeros(3),
                  'up': np.array([0.,0.,1.]), 'fov': 30}
        return renderer, camera

    def test_clear_layer_keeps_ground_and_lights_exact_for_all_strengths(self):
        cloud = np.zeros((32,64,4),np.uint8)
        renderer, camera = self.render_layer(cloud,np.full((32,64),12,np.float32))
        try:
            a = renderer.render(camera,[1.,0.,0.],enabled=False,relief_strength=0)
            b = renderer.render(camera,[1.,0.,0.],enabled=False,relief_strength=.35,night_depth_strength=1.)
            np.testing.assert_array_equal(a,b)
            self.assertTrue((a == 80).all())
            np.testing.assert_array_equal(a,renderer.render(camera,[-1.,0.,0.],enabled=False,
                relief_strength=.35,night_depth_strength=1.))
        finally: renderer.close()

    def test_flat_cloud_overlay_matches_independent_display_over(self):
        cloud = np.full((32,64,4), [200,140,100,128], np.uint8)
        renderer, camera = self.render_layer(cloud,np.full((32,64),12,np.float32))
        try:
            a = renderer.render(camera,[1.,0.,0.],enabled=False,relief_strength=0)
            expected = np.array([200,140,100])*128/255+80*(1-128/255)
            self.assertLessEqual(abs(a[32,32]-expected).max(),1.1)
            b = renderer.render(camera,[1.,0.,0.],enabled=False,relief_strength=.35)
            self.assertTrue(np.isfinite(b).all())
            np.testing.assert_array_equal(b,renderer.render(camera,[1.,0.,0.],enabled=False,relief_strength=.35))
        finally: renderer.close()
