"""Lossless cache of the static night input on an exact target grid."""
import hashlib
import json
from pathlib import Path
import numpy as np
import rasterio
from .archive import sha
from .project import save

_verified={}


def read(path,area,folder,loader):
    path=Path(path); folder=Path(folder)
    with rasterio.open(path) as source:
        files=sorted(set([str(path),*source.files]))
    identity={'version':3,'crs':area.crs.to_wkt(),'shape':list(area.shape),
              'extent':list(area.area_extent),'nearest_warp_tolerance':1e-9,
              'sources':[{ 'file':name,'size':Path(name).stat().st_size,
                           'mtime_ns':Path(name).stat().st_mtime_ns} for name in files]}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    target=folder/(key+'.npy'); receipt=folder/(key+'.json')
    if receipt.exists():
        record=json.loads(receipt.read_text(encoding='utf-8'))
        stamp=(target.stat().st_size,target.stat().st_mtime_ns)
        if record['identity']!=identity: raise ValueError('Night cache grid/source identity changed')
        if _verified.get(str(target))!=stamp:
            if sha(target)!=record['sha256']: raise ValueError('Night cache checksum failed; preserved')
            _verified[str(target)]=stamp
        values=np.load(target,mmap_mode='r',allow_pickle=False)
        if values.dtype!=np.float32 or values.shape!=(3,*area.shape):
            raise ValueError('Night cache dtype/shape differs; preserved')
        return values
    folder.mkdir(parents=True,exist_ok=True)
    part=target.with_suffix('.part.npy')
    if area.width*area.height>=5_000_000:
        values=np.lib.format.open_memmap(part,mode='w+',dtype=np.float32,shape=(3,*area.shape))
        loader(path,area,out=values)
        values.flush(); values._mmap.close(); del values
    else:
        values=loader(path,area)
        with part.open('wb') as stream: np.save(stream,values,allow_pickle=False)
        del values
    part.replace(target)
    save(receipt,{'identity':identity,'sha256':sha(target),'operation':'Exact float32 static input; no resampling on cache reuse'})
    _verified[str(target)]=(target.stat().st_size,target.stat().st_mtime_ns)
    return np.load(target,mmap_mode='r',allow_pickle=False)
