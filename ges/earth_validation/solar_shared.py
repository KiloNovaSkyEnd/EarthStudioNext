"""Reuse identical stock solar correction factors across same-scan bands.

No persistent cache and no rounded position/time keys. Dask deduplicates only
equal angle graphs, parameters and signal dtypes in the current computation.
The installed Satpy ndarray implementation generates each factor unchanged.
"""
import dask.array as da
import numpy as np
from threading import Lock
from satpy.modifiers.geometry import SunZenithCorrector,SunZenithReducer
from satpy.modifiers.angles import _sunzen_corr_cos_ndarray,_sunzen_reduction_ndarray

factor_sample={}
_sample_lock=Lock()


def record_factor(kind,size):
    with _sample_lock:
        factor_sample[kind+'_calls']=factor_sample.get(kind+'_calls',0)+1
        factor_sample[kind+'_pixels']=factor_sample.get(kind+'_pixels',0)+size


def cos_factor_block(coszen,signal_dtype,limit,max_sza):
    record_factor('cos',coszen.size)
    ones=np.ones(coszen.shape,dtype=np.dtype(signal_dtype))
    return _sunzen_corr_cos_ndarray(ones,coszen,limit,max_sza)


def reduction_factor_block(sunz,signal_dtype,limit,max_sza,strength):
    record_factor('reduction',sunz.size)
    ones=np.ones(sunz.shape,dtype=np.dtype(signal_dtype))
    return _sunzen_reduction_ndarray(ones,sunz,limit,max_sza,strength)


class SharedSunZenithCorrector(SunZenithCorrector):
    def _apply_correction(self,proj,coszen):
        factor=da.map_blocks(cos_factor_block,coszen.data,proj.dtype.str,
            self.correction_limit,self.max_sza,dtype=proj.dtype,
            meta=np.empty((0,0),dtype=proj.dtype))
        result=proj.copy(deep=False)
        result.data=proj.data*factor
        return result


class SharedSunZenithReducer(SunZenithReducer):
    def _apply_correction(self,proj,coszen):
        sunz=np.rad2deg(np.arccos(coszen.data))
        dtype=np.result_type(proj.dtype,sunz.dtype)
        factor=da.map_blocks(reduction_factor_block,sunz,proj.dtype.str,
            self.correction_limit,self.max_sza,self.strength,dtype=dtype,
            meta=np.empty((0,0),dtype=dtype))
        result=proj.copy(deep=False)
        result.data=proj.data*factor
        return result
