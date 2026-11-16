import unittest
import numpy as np
from pyresample import create_area_def
from ges.geosampling import native_indices,sample_native,limb_visibility


class GeosamplingTests(unittest.TestCase):
    def setUp(self):
        self.area=create_area_def('test_geos',{'proj':'geos','lon_0':140.7,'h':35785863,
            'a':6378137,'b':6356752.3,'sweep':'y'},shape=(64,64),
            area_extent=(-5500000,-5500000,5500000,5500000),units='m')

    def test_actual_grid_roundtrip_and_dateline(self):
        xx=np.array([20,32,40]);yy=np.array([30,32,40])
        lon,lat=self.area.get_lonlat_from_array_coordinates(xx,yy)
        ix,iy,valid=native_indices(self.area,lon,lat)
        self.assertTrue(valid.all());np.testing.assert_array_equal(ix,xx);np.testing.assert_array_equal(iy,yy)
        a=native_indices(self.area,180,0);b=native_indices(self.area,-180,0)
        for x,y in zip(a,b):np.testing.assert_array_equal(x,y)

    def test_far_hemisphere_and_invalid_targets_not_assigned(self):
        _,_,valid=native_indices(self.area,np.array([-39.3,np.nan,140.7]),np.array([0,0,91]))
        self.assertFalse(valid.any())

    def test_missing_native_pixel_does_not_borrow_neighbor(self):
        values=np.full(self.area.shape,280,dtype=np.float32);values[32,32]=np.nan
        lon,lat=self.area.get_lonlat_from_array_coordinates(np.array([32,33]),np.array([32,32]))
        out=sample_native(self.area,[values],lon,lat)[0]
        self.assertTrue(np.isnan(out[0]));self.assertEqual(out[1],280)
        masked=np.ma.array(np.full(self.area.shape,280,dtype=np.int16),mask=np.zeros(self.area.shape,dtype=bool))
        masked.mask[32,32]=True
        masked_out=sample_native(self.area,[masked],lon,lat)[0]
        self.assertTrue(np.isnan(masked_out[0]));self.assertEqual(masked_out[1],280)
        with self.assertRaises(ValueError):sample_native(self.area,[np.ones((2,2))],lon,lat)

    def test_limb_fade_is_central_identity_and_does_not_create_coverage(self):
        fade=limb_visibility(self.area,140.7,np.array([0,30,60,79,80,85]))
        np.testing.assert_array_equal(fade[:3],np.ones(3))
        self.assertTrue(0<fade[3]<1);self.assertLess(fade[4],fade[3]);self.assertEqual(fade[5],0)
