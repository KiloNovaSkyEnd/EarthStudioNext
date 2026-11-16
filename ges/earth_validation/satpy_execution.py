"""Equivalent stock low-cloud math without Dask's expensive indexed assignment.

Satpy 0.60 LowCloudCompositor builds a very large graph for ``res.loc['A'] =``.
Only the assembly of its final LA array differs here. All thresholding, gamma,
land/water rules and cold-cloud filtering are the stock operations.
"""
import xarray as xr
import numpy as np
import os
from satpy.composites.mask import CloudCompositor, LowCloudCompositor, HighCloudCompositor


class BoundedHighCloudCompositor(HighCloudCompositor):
    """Stock latitude thresholds, with a lazy initial NaN array instead of 4GB."""
    def __call__(self,projectables,**kwargs):
        if os.environ.get('EARTHSTUDIO_H9_CUDA_CLOUDS')=='1':
            from .cuda_clouds import high
            return high(self,projectables,kwargs)
        if len(projectables)!=1: raise ValueError(f'Expected 1 dataset, got {len(projectables)}')
        data=projectables[0]
        _,lats=data.attrs['area'].get_lonlats(chunks=data.chunks,dtype=data.dtype)
        lats=np.abs(lats)
        slope=(self.transition_min_limits[1]-self.transition_min_limits[0])/(self.latitude_min_limits[1]-self.latitude_min_limits[0])
        offset=self.transition_min_limits[0]-slope*self.latitude_min_limits[0]
        transition_min=xr.full_like(data,np.nan).rename('transition_min')
        transition_min.attrs={}
        transition_min=transition_min.where(lats>=self.latitude_min_limits[0],self.transition_min_limits[0])
        transition_min=transition_min.where(lats<=self.latitude_min_limits[1],self.transition_min_limits[1])
        transition_min=transition_min.where((lats<self.latitude_min_limits[0])|
            (lats>self.latitude_min_limits[1]),slope*lats+offset)
        self.transition_min=transition_min
        return CloudCompositor.__call__(self,projectables,**kwargs)


class BoundedLowCloudCompositor(LowCloudCompositor):
    def __call__(self, projectables, **kwargs):
        if os.environ.get('EARTHSTUDIO_H9_CUDA_CLOUDS')=='1':
            from .cuda_clouds import low
            return low(self,projectables,kwargs)
        if len(projectables) != 3:
            raise ValueError(f'Expected 3 datasets, got {len(projectables)}')
        btd, bt_win, lsm = self.match_data_arrays(projectables)
        lsm = lsm.squeeze(drop=True).round()
        self.transition_min, self.transition_max = self.range_land
        result = CloudCompositor.__call__(self, [btd.where(lsm.isin(self.values_land))], **kwargs)
        self.transition_min, self.transition_max = self.range_water
        water = CloudCompositor.__call__(self, [btd.where(lsm.isin(self.values_water))], **kwargs)
        result = result.where(lsm.isin(self.values_land), water)
        luminance = result.sel(bands='L', drop=True)
        alpha = result.sel(bands='A', drop=True).where(bt_win >= 230, 0.0)
        assembled = xr.concat([luminance, alpha], dim=xr.IndexVariable('bands', ['L', 'A']))
        assembled = assembled.transpose(*result.dims)
        assembled.attrs = result.attrs.copy()
        return assembled
