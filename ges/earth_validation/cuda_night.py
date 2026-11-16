"""Fuse the installed stock night cloud/enhancement/overlay equations on CUDA."""
from functools import lru_cache
import os
from time import perf_counter
import numpy as np
import dask.array as da
import xarray as xr
from satpy.composites.fill import BackgroundCompositor
from satpy.composites.core import GenericCompositor,enhance2dataset
from satpy.enhancements.enhancer import get_enhanced_image
from .cuda_clouds import runtime,_lock
from . import resources

@lru_cache(maxsize=2)
def installed_enhancement_constants(dtype):
    def sample(name,bands):
        values=np.ones((len(bands),1,2),dtype=dtype)
        return xr.DataArray(da.from_array(values),dims=('bands','y','x'),coords={'bands':list(bands)},
            attrs={'name':name,'standard_name':name,'mode':bands})
    high=get_enhanced_image(sample('geo_color_high_clouds','LA'))
    night=get_enhanced_image(sample('night_background','RGB'))
    low=enhance2dataset(sample('geo_color_low_clouds','LA')).compute()
    history=high.data.attrs['enhancement_history'][0]
    night_history=night.data.attrs['enhancement_history'][0]
    return tuple(float(v) for v in [history['scale'].sel(bands='L').item(),history['offset'].sel(bands='L').item(),
        night_history['scale'].sel(bands='R').item(),night_history['offset'].sel(bands='R').item(),
        *low.sel(bands=['R','G','B']).values[:,0,0]])

@lru_cache(maxsize=4)
def kernel(dtype,night_dtype):
    cp=runtime();high_scale,high_offset,night_scale,night_offset,*colors=installed_enhancement_constants(dtype)
    # The native thermal calibration is float64, while the static night input
    # is float32. Stock Satpy enhances the latter BEFORE alpha compositing
    # promotes it to thermal precision. Preserve that rounding boundary.
    _,_,night_scale,night_offset,*_=installed_enhancement_constants(night_dtype)
    code='''
      T a_low = btd <= T(0) ? T(1) : (btd > T(4) ? T(0) : T(-0.25)*btd+T(1));
      a_low=T(1)-a_low;
      if (!(mask == T(100) || mask == T(0)) || !(ir >= T(230)) || isnan(a_low)) a_low=T(0);
      T lat=fabs(latitude);
      T lo=lat<T(30) ? T(210) : (lat>T(60) ? T(230) : T(20.0/30.0)*lat+T(190));
      T slope=T(1)/(lo-T(300)); T offset=T(1)-slope*lo;
      T a_high=ir<=lo ? T(1) : (ir>T(300) ? T(0) : slope*ir+offset);
      a_high=a_high<T(0) ? T(0) : (a_high>T(1) ? T(1) : a_high);
      if (isnan(a_high)) a_high=T(0);
    '''
    code+=f'T high=ir*T({high_scale!r})+T({high_offset!r});\n'
    code+='high=high<T(0) ? T(0) : (high>T(1) ? T(1) : high);\n'
    for source,dest,color in zip(['red','green','blue'],['r','g','b'],colors):
        code+=f'''
          U enhanced_{dest}={source}*U({night_scale!r})+U({night_offset!r});
          enhanced_{dest}=enhanced_{dest}<U(0) ? U(0) : (enhanced_{dest}>U(1) ? U(1) : enhanced_{dest});
          T bg_{dest}=T(enhanced_{dest});
          T low_{dest}=(T({color!r})*a_low+bg_{dest}*T(1)*(T(1)-a_low))/(a_low+T(1)*(T(1)-a_low));
          if (isnan(low_{dest})) low_{dest}=bg_{dest}*T(1);
          low_{dest}=low_{dest}<T(0) ? T(0) : (low_{dest}>T(1) ? T(1) : low_{dest});
          {dest}=(high*a_high+low_{dest}*T(1)*(T(1)-a_high))/(a_high+T(1)*(T(1)-a_high));
          if (isnan({dest})) {dest}=low_{dest}*T(1);
        '''
    return cp.ElementwiseKernel('T ir,T btd,T mask,T latitude,U red,U green,U blue','T r,T g,T b',
        code,'stock_night_layers',options=('--fmad=false',))

def block(ir,btd,mask,lats,red,green,blue):
    with _lock:
        cp=runtime();began=perf_counter()
        inputs=[cp.asarray(np.ascontiguousarray(v),dtype=ir.dtype) for v in [ir,btd,mask,lats]]
        inputs.extend(cp.asarray(np.ascontiguousarray(v)) for v in [red,green,blue])
        operation=kernel(str(ir.dtype),str(red.dtype))
        event0,event1=cp.cuda.Event(),cp.cuda.Event();event0.record()
        stacked=cp.stack(operation(*inputs));event1.record()
        result=cp.asnumpy(stacked);event1.synchronize()
        elapsed=perf_counter()-began
        kernel_ms=cp.cuda.get_elapsed_time(event0,event1)
        sample=resources.gpu_sample
        sample.update(backend='cuda-stock-night-layers',calls=sample.get('calls',0)+1,
            pixels=sample.get('pixels',0)+ir.size,last_transfer_and_compute_seconds=elapsed,
            last_kernel_ms=kernel_ms,total_kernel_ms=sample.get('total_kernel_ms',0)+kernel_ms,
            total_transfer_and_compute_seconds=sample.get('total_transfer_and_compute_seconds',0)+elapsed,
            pool_reserved_bytes=cp.get_default_memory_pool().total_bytes())
        return result

class CudaNightBackgroundCompositor(BackgroundCompositor):
    def __call__(self,projectables,optional_datasets=None,**kwargs):
        if os.environ.get('EARTHSTUDIO_H9_CUDA_CLOUDS')!='2':
            return super().__call__(projectables,**kwargs)
        if optional_datasets is None or len(optional_datasets)!=4:
            raise ValueError('Stock CUDA night fusion requires all four actual prerequisites')
        ir,btd,mask,night=self.match_data_arrays(optional_datasets)
        mask=mask.squeeze(drop=True).round()
        chunks=ir.data.rechunk((1024,1024)).chunks
        _,lats=ir.attrs['area'].get_lonlats(chunks=chunks,dtype=ir.dtype)
        inputs=[v.data.rechunk(chunks) for v in [ir,btd,mask]]+[lats]+[night.sel(bands=c).data.rechunk(chunks) for c in ['R','G','B']]
        lazy=da.map_blocks(block,*inputs,dtype=ir.dtype,chunks=((3,),)+chunks,new_axis=0,
            meta=np.empty((0,0,0),dtype=ir.dtype))
        data=[xr.DataArray(lazy[i],dims=ir.dims,coords=ir.coords,attrs=ir.attrs.copy()) for i in range(3)]
        return GenericCompositor.__call__(self,data,**kwargs)
