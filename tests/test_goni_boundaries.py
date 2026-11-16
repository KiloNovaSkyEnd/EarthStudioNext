import unittest
import numpy as np
from scripts.soften_goni_boundaries import inward_feather


class BoundaryDisplayTests(unittest.TestCase):
    def test_mask_hole_stays_empty_and_interior_stays_opaque(self):
        support=np.ones((15,15),bool);support[7,7]=False;original=support.copy()
        weight=inward_feather(support)
        self.assertEqual(weight[7,7],0)
        self.assertEqual(weight[7,8],.5)
        self.assertEqual(weight[7,10],1)
        np.testing.assert_array_equal(support,original)
        self.assertFalse(np.any((weight>0)&~support))

    def test_missing_image_cannot_become_cloud(self):
        np.testing.assert_array_equal(inward_feather(np.zeros((12,18),bool)),np.zeros((12,18)))
