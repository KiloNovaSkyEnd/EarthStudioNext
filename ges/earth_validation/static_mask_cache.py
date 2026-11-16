"""Memoize the exact stock nearest land/water mask, never weather observations."""
import hashlib
import json
from pathlib import Path
import dask.array as da
import numpy as np
import satpy
from satpy import Scene
from satpy.resample.base import _update_resampled_coords
import xarray as xr
from .arrays import ReadOnlyArray
from .archive import sha
from .project import save,check_disk
from .spill import bounded_compute
from .compute_progress import ComputeProgress

_verified={}


def cached(data,target,reference,folder,compute_chunk=512):
    if data.attrs.get('standard_name')!='land_water_mask':
        raise ValueError('Only static land/water mask may use this cache')
    reference=Path(reference); folder=Path(folder); root=folder.parent.parent
    source=data.attrs['area']
    identity={'version':1,'satpy':satpy.__version__,'source_sha256':sha(reference),
        'source_grid':[source.crs.to_wkt(),list(source.shape),list(source.area_extent)],
        'target_grid':[target.crs.to_wkt(),list(target.shape),list(target.area_extent)],
        'dtype':str(data.dtype),'dims':list(data.dims),'method':'stock-nearest','radius_m':6000}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    path=folder/(key+'.npy'); receipt=folder/(key+'.json')
    if receipt.exists():
        record=json.loads(receipt.read_text(encoding='utf-8'))
        stamp=(path.stat().st_size,path.stat().st_mtime_ns)
        if record['identity']!=identity: raise ValueError('Static mask identity changed')
        if _verified.get(str(path))!=stamp:
            if sha(path)!=record['sha256']: raise ValueError('Static mask cache checksum failed; preserved')
            _verified[str(path)]=stamp
    else:
        shape=tuple(target.height if d=='y' else target.width if d=='x' else data.sizes[d] for d in data.dims)
        check_disk(root,int(np.prod(shape))*data.dtype.itemsize)
        folder.mkdir(parents=True,exist_ok=True)
        # Isolate this static graph so its tree/intermediates can be freed before
        # constructing the final RGB graph. Same stock resampler and parameters.
        name=data.attrs.get('name','static_mask')
        temporary=Scene(); temporary[name]=data.copy(deep=False)
        aligned=temporary.resample(target,datasets=[name],generate=False,
            resampler='nearest',radius_of_influence=6000)[name]
        part=path.with_suffix('.part.npy')
        values=np.lib.format.open_memmap(part,mode='w+',dtype=data.dtype,shape=shape)
        with bounded_compute(root),ComputeProgress(root/'reports/static_mask_progress.json','static-land-water-mask'):
            da.store(aligned.data,values,lock=True)
        values.flush(); values._mmap.close(); del values,aligned,temporary
        part.replace(path)
        save(receipt,{'identity':identity,'sha256':sha(path),'operation':'Exact original stock nearest output, no precision reduction'})
        _verified[str(path)]=(path.stat().st_size,path.stat().st_mtime_ns)
    values=np.load(path,mmap_mode='r',allow_pickle=False)
    lazy=da.from_array(ReadOnlyArray(values),chunks=tuple(compute_chunk if d in ('x','y') else data.sizes[d] for d in data.dims),
        asarray=False,fancy=False,name=False,meta=np.empty((0,)*data.ndim,dtype=data.dtype))
    x,y=target.get_proj_vectors()
    output=xr.DataArray(lazy,dims=data.dims,name=data.name,coords={'x':x,'y':y},attrs=data.attrs.copy())
    output.attrs['area']=target
    return _update_resampled_coords(data,output,target)
