import unittest
import numpy as np
import json
from pathlib import Path
from pyresample.geometry import AreaDefinition
from ges.seviri_cloud_evidence import seviri_classes,area_from_points
from ges.cloud_evidence import evidence_rgba


class SeviriCloudEvidenceTests(unittest.TestCase):
    def test_real_grib_geolocation_rejects_legacy_flip_and_coarse_offset(self):
        rows=json.loads((Path(__file__).parent/'fixtures/seviri_grib_navigation_20201029.json').read_text())
        for row in rows:
            area=AreaDefinition('legacy','legacy','geos',row['crs_wkt'],row['shape'][1],row['shape'][0],row['native_area_extent'])
            xy=np.asarray(row['xy']);oldlon,oldlat=area.get_lonlat_from_array_coordinates(xy[:,0],xy[:,1])
            self.assertGreater(float(abs(oldlat-np.array(row['lat'])).max()),1)
            fixed,check=area_from_points(area,tuple(row['shape']),xy,row['lon'],row['lat'])
            self.assertLess(check['max_geolocation_error_deg'],.00001)
            self.assertGreater(fixed.pixel_size_x,0);self.assertGreater(fixed.pixel_size_y,0)

    def test_real_seviri_mask_quality_height_crop(self):
        with np.load(Path(__file__).parent/'fixtures/seviri_cloud_support_20201029.npz') as d:
            c=seviri_classes(d['cloud_mask'],d['cloud_top_height'],d['cloud_top_quality'])
            self.assertEqual(int((c==9).sum()),4096)
            damaged=d['cloud_top_quality'].copy();damaged[:]=1
            rejected=seviri_classes(d['cloud_mask'],d['cloud_top_height'],damaged)
            self.assertFalse((rejected==9).any())

    def test_mask_height_quality_and_missing_values_gate_low_clouds(self):
        c=seviri_classes(np.array([2,2,2,2,2,0,1,3]),
                         np.array([1200,2999,3000,1200,np.nan,1200,1200,1200]),
                         np.array([0,0,0,1,0,0,0,0]))
        np.testing.assert_array_equal(c,[9,9,3,3,3,1,1,0])
        r=evidence_rgba(np.full(8,275),c,np.ones(8,dtype=bool))
        np.testing.assert_array_equal(r[:,2]>r[:,0],[True,True,False,False,False,False,False,False])
        with self.assertRaises(ValueError):seviri_classes([2],[1000,2000],[0])
