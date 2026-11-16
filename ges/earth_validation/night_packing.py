"""Lossless tiled storage of integer RGB night inputs plus the exact NaN mask.

The original float32 grid stays intact. Only I/O representation changes; every
decoded float32 bit is checked before publication. Scientific input remains RGB
float32 0..255/NaN, at the identical original target pixel coordinates.
"""
import json
from pathlib import Path
from numbers import Integral
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.windows import Window
from .archive import sha
from .project import save,check_disk

_verified={}


class PackedNight:
    dtype=np.dtype('float32')
    ndim=3
    def __init__(self,path,shape): self.path=Path(path); self.shape=tuple(shape)

    def __getitem__(self,index):
        items=list(index if isinstance(index,tuple) else (index,))
        if any(v is Ellipsis for v in items):
            where=next(i for i,v in enumerate(items) if v is Ellipsis)
            items[where:where+1]=[slice(None)]*(4-len(items))
        items += [slice(None)]*(3-len(items))
        if len(items)!=3 or any(not isinstance(v,(slice,Integral)) for v in items):
            raise IndexError('Packed night supports ordinary array windows only')
        positions=[np.atleast_1d(np.arange(n)[v]) for n,v in zip(self.shape,items)]
        dropped=tuple(i for i,v in enumerate(items) if isinstance(v,Integral))
        if any(len(v)==0 for v in positions):
            result=np.empty(tuple(len(v) for v in positions),np.float32)
        else:
            bands,rows,cols=positions
            r0,r1=int(rows.min()),int(rows.max())+1; c0,c1=int(cols.min()),int(cols.max())+1
            with rasterio.open(self.path) as source:
                window=Window(c0,r0,c1-c0,r1-r0)
                result=source.read([int(b)+1 for b in bands],window=window).astype(np.float32)
                valid=source.read(4,window=window)>0
            result[:,~valid]=np.float32(np.nan)
            result=result[np.ix_(np.arange(len(bands)),rows-r0,cols-c0)]
        if dropped: result=result.squeeze(axis=dropped)
        return result[()] if result.ndim==0 else result


def packed(values):
    path=Path(values.filename); target=path.with_suffix('.rgba.tif'); receipt=path.with_suffix('.rgba.json')
    original_receipt=path.with_suffix('.json')
    source_record=json.loads(original_receipt.read_text(encoding='utf-8')) if original_receipt.exists() else {}
    source_sha=source_record.get('sha256') or sha(path)
    identity={'version':1,'source_float32_sha256':source_sha,'shape':list(values.shape)}
    if values.dtype!=np.float32 or values.shape[0]!=3: raise ValueError('Expected original float32 RGB grid')
    if receipt.exists():
        record=json.loads(receipt.read_text(encoding='utf-8'))
        stamp=(target.stat().st_size,target.stat().st_mtime_ns)
        if record['identity']!=identity: raise ValueError('Packed night source identity changed')
        if _verified.get(str(target))!=stamp:
            if sha(target)!=record['sha256']: raise ValueError('Packed night checksum failed; preserved')
            _verified[str(target)]=stamp
        return PackedNight(target,values.shape)
    height,width=values.shape[1:]
    # Production files are project/processed/static_night_grids_v1; fixtures
    # exercise the codec directly without performing any download.
    if path.parent.name=='static_night_grids_v1': check_disk(path.parent.parent.parent,height*width*4)
    part=target.with_suffix('.part.tif')
    geography={}
    grid=source_record.get('identity',{})
    if grid.get('crs') and grid.get('extent'):
        geography={'crs':grid['crs'],'transform':from_bounds(*grid['extent'],width,height)}
    with rasterio.open(part,'w',driver='GTiff',width=width,height=height,count=4,dtype='uint8',
        tiled=True,blockxsize=256,blockysize=256,compress='DEFLATE',predictor=2,zlevel=1,**geography) as output:
        for row in range(0,height,128):
            block=values[:,row:row+128]
            finite=np.isfinite(block)
            if not np.array_equal(finite[0],finite[1]) or not np.array_equal(finite[0],finite[2]):
                raise ValueError('Night RGB channels have different missing masks; original preserved')
            valid=finite[0]; data=np.where(valid[None],block,0)
            if np.any(data<0) or np.any(data>255) or np.any(data!=np.floor(data)):
                raise ValueError('Night RGB is not integral0..255; refusing precision reduction')
            rgba=np.empty((4,*block.shape[1:]),np.uint8)
            rgba[:3]=data.astype(np.uint8); rgba[3]=valid*255
            output.write(rgba,window=Window(0,row,width,block.shape[1]))
    # Verify every original pixel/channel, including NaN payload bits.
    reader=PackedNight(part,values.shape)
    for row in range(0,height,128):
        decoded=reader[:,row:row+128,:]
        if not np.array_equal(values[:,row:row+128].view(np.uint32),decoded.view(np.uint32)):
            raise ValueError('Packed night float32 bits changed; original preserved')
    part.replace(target)
    save(receipt,{'identity':identity,'sha256':sha(target),'all_float32_bits_verified':True,
        'verified_rgb_values':int(np.prod(values.shape)),'bytes':target.stat().st_size,
        'operation':'Lossless original RGB integers and exact NaN mask, no spatial resampling'})
    _verified[str(target)]=(target.stat().st_size,target.stat().st_mtime_ns)
    return PackedNight(target,values.shape)
