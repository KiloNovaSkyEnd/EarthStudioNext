"""Separate actual VIS tone from model opacity; keep spectral night unchanged."""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import h5py
import numpy as np
from PIL import Image
from ges.catalog import utc_time
from ges.download import read_manifest
from ges.goni_data import SLICE,decode
from ges.goni_lowcloud import daylight_material
from ges.range_archive import RangeArchive
from ges.render import create_satpy_scene
from ges.solar import solar_weights
from ges.storage import load_config
from scripts.restore_goni_spectral import Offline


def refine(item):
    cfg=load_config();stamp=utc_time(item['nominal_utc']);root=cfg.processed_dir/'goni_film_v1/frames'/stamp.strftime('%Y%m%dT%H%MZ');path=root/'frame.json'
    began=time.monotonic()
    while True:
        try:m=json.loads(path.read_text())
        except (FileNotFoundError,json.JSONDecodeError):m={}
        if m.get('material_revision',0)>=5:break
        if time.monotonic()-began>7200:raise TimeoutError('Spectral material not ready')
        time.sleep(5)
    if m.get('material_revision')==6 and m.get('daylight_restoration',{}).get('roi_tone_feather',m['vis'] is None):return m
    if m['vis'] is None:
        m['material_revision']=6;m['daylight_restoration']={'vis_used':False,'night_material_unchanged':True}
    else:
        original=read_manifest(Path(m['source_manifest']));scene=create_satpy_scene([p for p in original['local_files'] if '_B03_' in Path(p).name],'himawari8');scene.load(['B03'])
        vis=scene['B03'];area=vis.attrs['area'];r0,r1,c0,c1=m['lowcloud_restoration']['roi_native_yx'];y0,y1,x0,x1=SLICE
        # VIS source area has4x the IR row/column count, same projection/extent.
        if vis.shape!=(22000,22000) or vis.attrs['units']!='%':raise ValueError('Actual500m VIS required')
        values=vis.data[r0*4:r1*4,c0*4:c1*4].astype(np.float32)
        v=np.ma.filled(values.reshape(((r1-r0)*2,2,(c1-c0)*2,2)).mean(axis=(1,3),dtype=np.float32).compute(scheduler='single-threaded'),np.nan).astype(np.float32)/100
        with np.load(root/'lowcloud_evidence_v4.npz') as f:p=f['cloud_probability'].copy()
        record=next(r for r in m['lowcloud_restoration']['sources'] if r['key'].endswith('_CLOUD_MASK_EN.nc'))
        with RangeArchive(Offline(),'noaa-himawari8',record['key'],record['remote_bytes'],record['etag'],Path(record['archive']),cfg,max_bytes=0,block_size=65536) as stream:
            with h5py.File(stream,'r') as f:
                mask=decode(f['CloudMask'],np.s_[r0:r1,c0:c1],stream);q=decode(f['CloudMaskQualFlag'],np.s_[r0:r1,c0:c1],stream)
        yy,xx=np.indices(p.shape);edge=np.minimum.reduce([yy+1,xx+1,p.shape[0]-yy,p.shape[1]-xx]);blend=np.clip(edge/16,0,1);blend=blend*blend*(3-2*blend)
        p=np.where(np.isfinite(p)&(p>=0)&(p<=1)&(q==0)&np.isin(mask,[0,1,2,3]),np.isin(mask,[2,3])*(1-blend)+p*blend,0).astype(np.float32)
        source=root/'cloud_spectral_v5.png'
        if not source.exists():source=root/'cloud_lowcloud_v4.png'
        old=np.asarray(Image.open(source).convert('RGBA')).copy();result=old.copy();changed=0
        for row in range(0,r1-r0,128):
            last=min(row+128,r1-r0);local_y=slice(row*2,last*2);sl=np.s_[(r0-y0+row)*2:(r0-y0+last)*2,(c0-x0)*2:(c1-x0)*2]
            # Native IR centres at VIS coordinates4*i+1.5, verified same CRS.
            lo,la=area.get_lonlat_from_array_coordinates(*np.meshgrid(np.arange(c0,c1)*4+1.5,np.arange(r0+row,r0+last)*4+1.5))
            geo=np.isfinite(lo)&np.isfinite(la);e=solar_weights(stamp,np.where(geo,lo,0),np.where(geo,la,0)).elevation_deg
            expand=lambda a:np.repeat(np.repeat(a,2,0),2,1)
            e=expand(e);p1=expand(p[row:last]*geo)
            a=np.clip(np.sin(np.deg2rad(e))/.25,0,1);day=a*a*a*(a*(a*6-15)+10)
            safe=np.maximum(np.sin(np.deg2rad(e)),np.sin(np.deg2rad(6)))
            radiance=np.where(np.isfinite(v[local_y])&(e>0),np.maximum(v[local_y]/safe,0),0)
            old_r=np.clip(radiance,0,1.2);old_alpha=np.clip(old_r/1.05,0,1)**.8*p1
            old_color=np.clip(.55+.45*np.sqrt(np.clip(old_r,0,1)),0,1)
            new_color,new_alpha=daylight_material(radiance,p1)
            region=expand(blend[row:last])
            new_premult=new_color*new_alpha*region+old_color*old_alpha*(1-region)
            new_alpha=old_alpha*(1-region)+new_alpha*region
            new_color=np.divide(new_premult,new_alpha,out=np.zeros_like(new_alpha),where=new_alpha>0)
            block=old[sl];alpha=block[...,3].astype(np.float32)/255
            remainder=np.maximum(alpha-old_alpha*day,0)
            premult=np.maximum(block[...,:3].astype(np.float32)/255*alpha[...,None]-(old_color*old_alpha*day)[...,None],0)
            total=remainder+new_alpha*day
            rgb=np.divide(premult+(new_color*new_alpha*day)[...,None],total[...,None],out=np.zeros_like(premult),where=total[...,None]>0)
            result[sl][...,:3]=np.rint(np.clip(rgb,0,1)*255).astype(np.uint8);result[sl][...,3]=np.rint(np.clip(total,0,1)*255).astype(np.uint8)
            result[sl][day==0]=block[day==0];changed+=int((day>0).sum())
        target=root/'cloud_daylight_v6.png';tmp=root/'cloud_daylight_v6.tmp.png';Image.fromarray(result).save(tmp,compress_level=3);tmp.replace(target)
        m['material_revision']=6;m['render_material_file']=target.name
        m['daylight_restoration']={'vis_used':True,'display_day_pixels':changed,'source':'original500m B03 area averaged to1km; same native ROI',
            'transfer':'RGB=(1-exp(-1.8*sun-normalized_reflectance))^(1/2.2); alpha=(1-exp(-5*reflectance))*cloud_probability',
            'hard_white_clipping':False,'modeled_not_retrieved_optical_depth':True,'fully_night_pixels_unchanged':True,'roi_tone_feather':True,
            'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(m,indent=2),encoding='utf-8');tmp.replace(path)
    print('DAY TONE',m['nominal_utc'],flush=True);return m


if __name__=='__main__':
    folder=load_config().processed_dir/'goni_film_v1';items=json.loads((folder/'inventory.json').read_text())['scenes']
    with ProcessPoolExecutor(max_workers=2) as pool:frames=list(pool.map(refine,items))
    (folder/'frames_daylight_v6.json').write_text(json.dumps(frames,indent=2),encoding='utf-8');print('DAYLIGHT READY31',flush=True)
