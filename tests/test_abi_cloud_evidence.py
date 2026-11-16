import unittest
import numpy as np
from ges.abi_cloud_evidence import nearest_axis,abi_classes
from ges.cloud_evidence import evidence_classes,evidence_rgba,LOW_CLASSES


class AbiCloudEvidenceTests(unittest.TestCase):
    def test_projection_coordinate_mapping_handles_descending_y_and_edges(self):
        ix,valid=nearest_axis(np.array([20,10,0]),np.array([26,24,15,9,-4,-6]))
        np.testing.assert_array_equal(valid,[False,True,True,True,True,False])
        np.testing.assert_array_equal(ix,[0,0,1,1,2,2])
        with self.assertRaises(ValueError):nearest_axis([0,3,2],[1])

    def test_abi_quality_clear_phase_and_nominal_low_pressure(self):
        c=abi_classes(np.array([1,1,1,0,1,1,1,1]),np.array([1,2,4,0,1,1,1,1]),
                      np.array([800,780,800,800,670,800,np.nan,800]),np.zeros(8),
                      np.array([0,0,0,0,0,1,0,0]),np.zeros(8),np.array([0,0,0,0,0,0,0,2]))
        np.testing.assert_array_equal(c,[8,8,3,1,3,3,3,3])
        rgba=evidence_rgba(np.full(8,270),c,np.ones(8,dtype=bool))
        np.testing.assert_array_equal(rgba[:,2]>rgba[:,0],[True,True,False,False,False,False,False,False])
        with self.assertRaises(ValueError):abi_classes(np.ones(3),*[np.ones(4)]*6)

    def test_ahi_nominal_low_retains_uncertainty_as_separate_class(self):
        args=[np.array([3,2,3,3,1]),np.ones(5),np.array([700,700,680,800,800]),
              np.array([40,40,10,30,30]),np.zeros(5),np.zeros(5),np.zeros(5)]
        strict=evidence_classes(*args);nominal=evidence_classes(*args,nominal_low=True)
        np.testing.assert_array_equal(strict,[3,4,3,2,4])
        np.testing.assert_array_equal(nominal,[7,7,3,2,4])
        self.assertTrue(np.isin(nominal[:2],LOW_CLASSES).all())

    def test_identical_measured_texture_has_identical_display_across_sensors(self):
        # Sensor-specific confidence is in labels, not different palettes.
        k=np.array([260,275,285],dtype=np.float32);low=np.array([.2,.6,1],dtype=np.float32)
        night=np.ones(3,dtype=bool)
        ahi=evidence_rgba(k,np.full(3,2),night,latitude=25,low_signal=low)
        abi=evidence_rgba(k,np.full(3,8),night,latitude=25,low_signal=low)
        np.testing.assert_array_equal(ahi,abi)
