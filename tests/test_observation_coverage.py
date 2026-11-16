import unittest
import numpy as np
import xarray as xr
from ges.earth_validation.coverage import observed_support


class ObservationCoverageTests(unittest.TestCase):
    def test_cold_auxiliary_gap_does_not_remove_observed_high_cloud(self):
        for visible, auxiliary, window in [('B03','B07','B13'), ('C02','C07','C13'),
                                            ('VIS006','IR_039','IR_108')]:
            scene={visible:xr.DataArray([1.,np.nan,1.,np.nan]),
                   auxiliary:xr.DataArray([np.nan,2.,2.,np.nan]),
                   window:xr.DataArray([195.,200.,np.nan,np.nan])}
            np.testing.assert_array_equal(observed_support(scene,list(scene)),[True,False,False,False])

    def test_all_primary_bands_are_still_required(self):
        scene={name:xr.DataArray([1.,1.]) for name in ['B01','B02','B03','B04','B13']}
        scene['B01'][1]=np.nan
        np.testing.assert_array_equal(observed_support(scene,list(scene)),[True,False])

    def test_only_auxiliary_is_not_evidence_of_coverage(self):
        with self.assertRaises(ValueError):
            observed_support({'B07':xr.DataArray([1.])},['B07'])
