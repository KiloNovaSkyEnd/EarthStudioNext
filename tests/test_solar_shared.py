"""Exact stock factors, mixed precision, NaNs/limits and graph reuse."""
import unittest
import dask
import dask.array as da
import numpy as np
import xarray as xr
from satpy.modifiers.geometry import SunZenithCorrector,SunZenithReducer
from ges.earth_validation.solar_shared import SharedSunZenithCorrector,SharedSunZenithReducer


class SolarSharedTests(unittest.TestCase):
    def test_exact_stock_outputs_for_precision_edges_and_missing_data(self):
        rng=np.random.default_rng(331)
        for signal_dtype,angle_dtype in [(np.float32,np.float32),(np.float32,np.float64),(np.float64,np.float64)]:
            signal=rng.normal(0,80,(43,51)).astype(signal_dtype)
            signal.flat[::37]=np.nan;signal.flat[::41]=-0.0
            degrees=rng.uniform(0,100,signal.shape).astype(angle_dtype)
            degrees.flat[:7]=[0,55,80,88,90,95,np.nan]
            cosine=np.cos(np.deg2rad(degrees))
            proj=xr.DataArray(da.from_array(signal,chunks=(13,17)),dims=('y','x'))
            coszen=xr.DataArray(da.from_array(cosine,chunks=(13,17)),dims=('y','x'))
            pairs=[(SunZenithCorrector,SharedSunZenithCorrector,dict(correction_limit=88.,max_sza=95.)),
                   (SunZenithCorrector,SharedSunZenithCorrector,dict(correction_limit=88.,max_sza=None)),
                   (SunZenithReducer,SharedSunZenithReducer,dict(correction_limit=80.,max_sza=90.,strength=1.3))]
            for ordinary,shared,options in pairs:
                with np.errstate(all='ignore'):
                    a=ordinary(name='fixture',**options)._apply_correction(proj,coszen).compute().values
                    b=shared(name='fixture',**options)._apply_correction(proj,coszen).compute().values
                self.assertEqual(a.dtype,b.dtype)
                np.testing.assert_array_equal(np.isnan(a),np.isnan(b))
                # Every non-NaN bit, including signed zero and infinities.
                finite=~np.isnan(a)
                np.testing.assert_array_equal(a[finite].view(np.uint8),b[finite].view(np.uint8))

    def test_same_angle_graph_factor_is_reused_across_real_different_signals(self):
        coszen=xr.DataArray(da.from_array(np.full((32,32),.4),chunks=(16,16)),dims=('y','x'))
        first=xr.DataArray(da.ones((32,32),chunks=(16,16)),dims=('y','x'))
        second=xr.DataArray(da.full((32,32),7.,chunks=(16,16)),dims=('y','x'))
        modifier=SharedSunZenithCorrector(name='fixture')
        a=modifier._apply_correction(first,coszen).data
        b=modifier._apply_correction(second,coszen).data
        factors_a={k for k in a.dask if isinstance(k,tuple) and k[0].startswith('cos_factor_block-')}
        factors_b={k for k in b.dask if isinstance(k,tuple) and k[0].startswith('cos_factor_block-')}
        self.assertEqual(len(factors_a),4)
        self.assertEqual(factors_a,factors_b)
        x,y=dask.compute(a,b)
        np.testing.assert_array_equal(x*7,y)
