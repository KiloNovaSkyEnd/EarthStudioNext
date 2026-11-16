import copy
import math
import unittest
from ges_next.camera import validate,basis,dot,horizontal_lens_mm


def track():
    return {'schema':'earthstudio.camera.v1','earthModel':'WGS84','coordinates':'ECEF_METERS','fps':30,'samples':[
        {'seconds':0,'position':[20_000_000,0,0],'direction':[-1,0,0],'up':[0,0,1],
         'verticalFov':math.pi/3,'aspect':16/9,'width':1920,'height':1080,'utc':'2026-10-20T22:40:00Z'}]}


class CameraTests(unittest.TestCase):
    def test_project_frame_rates_cross_export_boundary(self):
        for fps in [24,30,23.976,48]:
            value=track();value['fps']=fps
            self.assertIs(validate(value),value)
        for fps in [True,0,-1,float('nan'),121]:
            value=track();value['fps']=fps
            with self.assertRaises(ValueError):validate(value)

    def test_ecef_basis_maps_blender_negative_z_to_direction(self):
        right,up,back=basis([-1,0,0],[0,0,1])
        self.assertEqual(right,[0,1,0]); self.assertEqual(back,[1,0,0])
        self.assertEqual(dot(right,up),0)

    def test_roll_preserved(self):
        right,up,back=basis([-1,0,0],[0,1,0])
        self.assertEqual(up,[0,1,0]); self.assertEqual(right,[0,0,-1])

    def test_blender_lens_recovers_vertical_fov(self):
        s=track()['samples'][0]; lens=horizontal_lens_mm(s)
        self.assertAlmostEqual(2*math.atan(36/(2*lens*s['aspect'])),s['verticalFov'])

    def test_contract_rejects_invalid_pose_frustum_and_time(self):
        for key,value in [('direction',[0,0,0]),('position',[float('nan'),0,0]),('up',[-1,0,0]),('verticalFov',0),('aspect',1),('utc','2026-10-20T22:40:00'),('seconds',float('inf'))]:
            with self.subTest(key=key):
                t=track(); t['samples'][0][key]=value
                with self.assertRaises(ValueError): validate(t)

    def test_resize_and_reverse_time_rejected(self):
        for changes in [{'seconds':0},{'seconds':1,'width':960,'aspect':8/9}]:
            t=track(); second=copy.deepcopy(t['samples'][0]); second.update(changes); t['samples'].append(second)
            with self.assertRaises(ValueError): validate(t)

    def test_valid_single_pose_and_recording(self):
        self.assertIsNotNone(validate(track()))
        t=track(); s=copy.deepcopy(t['samples'][0]); s['seconds']=1/30; t['samples'].append(s)
        self.assertIsNotNone(validate(t))

    def test_recordings_longer_than_sixty_seconds(self):
        t=track();s=copy.deepcopy(t['samples'][0]);s['seconds']=3600;t['samples'].append(s)
        self.assertIsNotNone(validate(t))


if __name__=='__main__': unittest.main()
