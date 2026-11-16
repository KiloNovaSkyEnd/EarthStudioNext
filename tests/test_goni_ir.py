import unittest
import numpy as np
from ges.goni_data import refine_ir_material


class ColdCoreTests(unittest.TestCase):
    def test_original_bt_restores_variation_destroyed_by_old200k_clip(self):
        temperatures=np.array([[185.,195.,205.]],np.float32)
        cold=np.clip((300-temperatures)/100,0,1)
        alpha=.2+.78*cold**.8;rgb=.42+.43*cold
        old=np.empty((1,3,4),np.uint8);old[...,:3]=np.rint(rgb[...,None]*255);old[...,3]=np.rint(alpha*255)
        np.testing.assert_array_equal(old[0,0],old[0,1])
        new=refine_ir_material(old,temperatures,np.full_like(temperatures,-30),False)
        self.assertGreater(int(new[0,0,0]),int(new[0,1,0]))
        self.assertGreater(int(new[0,1,0]),int(new[0,2,0]))

    def test_selected_day_vis_and_missing_material_are_exactly_preserved(self):
        old=np.array([[[220,210,200,150],[0,0,0,0]]],np.uint8)
        new=refine_ir_material(old,np.array([[185.,190.]]),np.array([[45.,-30.]]))
        np.testing.assert_array_equal(new,old)
