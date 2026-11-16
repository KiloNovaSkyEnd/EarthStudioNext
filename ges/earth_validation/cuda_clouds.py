"""Optional CUDA execution of the installed stock cloud-mask equations.

No science constants or colormaps are changed. CPU calibration/navigation and
stock enhancements remain authoritative. Host/device transfers are included.
"""
from functools import lru_cache
from threading import Lock
from time import perf_counter
import numpy as np
import dask.array as da
import xarray as xr
from satpy.composites.core import GenericCompositor
from . import resources

_lock=Lock()

@lru_cache(maxsize=1)
def runtime():
    import cupy as cp
    assert int(cp.asnumpy(cp.arange(16).sum()))==120
    cp.get_default_memory_pool().set_limit(size=2*1024**3)
    prop=cp.cuda.runtime.getDeviceProperties(0)
    resources.gpu_sample.update(backend='cuda-stock-cloud-equations',device=prop['name'].decode(),calls=0,pixels=0)
    return cp

@lru_cache(maxsize=32)
def low_kernel(land,water,invert,gamma,lo_land,hi_land,lo_water,hi_water):
    cp=runtime()
    is_land=' || '.join(f'mask == T({v!r})' for v in land) or 'false'
    is_water=' || '.join(f'mask == T({v!r})' for v in water) or 'false'
    sl=1/(lo_land-hi_land);ol=1-sl*lo_land
    sw=1/(lo_water-hi_water);ow=1-sw*lo_water
    operation=f'''
        bool land = {is_land}; bool water = {is_water};
        T v = (land || water) ? btd : T(nan(""));
        T lo = land ? T({lo_land!r}) : T({lo_water!r});
        T hi = land ? T({hi_land!r}) : T({hi_water!r});
        T slope = land ? T({sl!r}) : T({sw!r});
        T offset = land ? T({ol!r}) : T({ow!r});
        T a = v <= lo ? T(1) : (v > hi ? T(0) : slope*v+offset);
        {'a=T(1)-a;' if invert else ''}
        {'a=pow(a,T('+repr(gamma)+'));' if gamma!=1 else ''}
        luminance=v; alpha=win >= T(230) ? a : T(0);
    '''
    return cp.ElementwiseKernel('T btd,T win,T mask','T luminance,T alpha',operation,'stock_low_cloud',options=('--fmad=false',))

@lru_cache(maxsize=32)
def high_kernel(temps,lats,trmax,gamma,invert):
    cp=runtime();slope=(temps[1]-temps[0])/(lats[1]-lats[0]);offset=temps[0]-slope*lats[0]
    operation=f'''
        T lat=fabs(latitude);
        T lo = lat < T({lats[0]!r}) ? T({temps[0]!r}) :
            (lat > T({lats[1]!r}) ? T({temps[1]!r}) : T({slope!r})*lat+T({offset!r}));
        T slope=T(1)/(lo-T({trmax!r})); T offset=T(1)-slope*lo;
        T a = value <= lo ? T(1) : (value > T({trmax!r}) ? T(0) : slope*value+offset);
        {'a=T(1)-a;' if invert else ''}
        {'a=pow(a,T('+repr(gamma)+'));' if gamma!=1 else ''}
        luminance=value;alpha=a;
    '''
    return cp.ElementwiseKernel('T value,T latitude','T luminance,T alpha',operation,'stock_high_cloud',options=('--fmad=false',))

def execute(kind,arrays,parameters):
    with _lock:
        cp=runtime();start=perf_counter()
        device=[cp.asarray(np.ascontiguousarray(a),dtype=arrays[0].dtype) for a in arrays]
        event0,event1=cp.cuda.Event(),cp.cuda.Event();event0.record()
        kernel=low_kernel(*parameters) if kind=='low' else high_kernel(*parameters)
        channels=kernel(*device);event1.record()
        result=cp.asnumpy(cp.stack(channels));event1.synchronize()
        sample=resources.gpu_sample
        sample.update(calls=sample.get('calls',0)+1,pixels=sample.get('pixels',0)+arrays[0].size,
            last_transfer_and_compute_seconds=perf_counter()-start,last_kernel_ms=cp.cuda.get_elapsed_time(event0,event1),
            pool_reserved_bytes=cp.get_default_memory_pool().total_bytes())
        return result

def low_block(btd,win,mask,parameters):return execute('low',[btd,win,mask],parameters)
def high_block(data,lats,parameters):return execute('high',[data,lats],parameters)

def assemble(compositor,data,lazy,kwargs):
    lum=xr.DataArray(lazy[0],dims=data.dims,coords=data.coords,attrs=data.attrs.copy())
    alpha=xr.DataArray(lazy[1],dims=data.dims,coords=data.coords,attrs=data.attrs.copy())
    return GenericCompositor.__call__(compositor,[lum,alpha],**kwargs)

def low(compositor,projectables,kwargs):
    if len(projectables)!=3:raise ValueError(f'Expected 3 datasets, got {len(projectables)}')
    btd,win,mask=compositor.match_data_arrays(projectables)
    mask=mask.squeeze(drop=True).round()
    inputs=[v.data.rechunk((1024,1024)) for v in (btd,win,mask)]
    inputs=[v.rechunk(inputs[0].chunks) for v in inputs]
    params=(tuple(float(v) for v in compositor.values_land),tuple(float(v) for v in compositor.values_water),
        compositor.invert_alpha,float(compositor.transition_gamma),*map(float,compositor.range_land),*map(float,compositor.range_water))
    lazy=da.map_blocks(low_block,*inputs,parameters=params,dtype=btd.dtype,
        chunks=((2,),)+inputs[0].chunks,new_axis=0,meta=np.empty((0,0,0),dtype=btd.dtype))
    compositor.transition_min,compositor.transition_max=compositor.range_water
    return assemble(compositor,btd,lazy,kwargs)

def high(compositor,projectables,kwargs):
    if len(projectables)!=1:raise ValueError(f'Expected 1 dataset, got {len(projectables)}')
    data=projectables[0];values=data.data.rechunk((1024,1024))
    _,lats=data.attrs['area'].get_lonlats(chunks=values.chunks,dtype=data.dtype)
    params=(tuple(map(float,compositor.transition_min_limits)),tuple(map(float,compositor.latitude_min_limits)),
        float(compositor.transition_max),float(compositor.transition_gamma),compositor.invert_alpha)
    lazy=da.map_blocks(high_block,values,lats,parameters=params,dtype=data.dtype,
        chunks=((2,),)+values.chunks,new_axis=0,meta=np.empty((0,0,0),dtype=data.dtype))
    return assemble(compositor,data,lazy,kwargs)
