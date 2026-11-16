"""Restore measured3.9/10.4um low-cloud texture with exact scan/night guards."""
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
from ges.goni_lowcloud import night_material,spectral_night_material
from ges.multispectral import calibrated_pair
from ges.range_archive import RangeArchive
from ges.solar import solar_weights
from ges.storage import load_config
from scripts.soften_goni_boundaries import inward_feather


class Offline:
    def get_object(self,**kwargs):raise RuntimeError('Spectral pass requires already archived mask bytes')


def restore(item):
    cfg=load_config();stamp=utc_time(item['nominal_utc']);root=cfg.processed_dir/'goni_film_v1/frames'/stamp.strftime('%Y%m%dT%H%MZ');meta_path=root/'frame.json'
    began=time.monotonic()
    while True:
        try:m=json.loads(meta_path.read_text())
        except (FileNotFoundError,json.JSONDecodeError):m={}
        if m.get('material_revision',0)>=4:break
        if time.monotonic()-began>7200:raise TimeoutError('Phase/height evidence not ready')
        time.sleep(5)
    if m.get('material_revision',0)>=5:return m
    if stamp.hour<7:
        m['material_revision']=5;m['spectral_restoration']={'shortwave_used':False,'reason':'daytime original VIS material retained'}
        tmp=meta_path.with_suffix('.tmp');tmp.write_text(json.dumps(m,indent=2),encoding='utf-8');tmp.replace(meta_path);return m
    supplement=cfg.raw_dir/('himawari8_goni_shortwave_'+stamp.strftime('%Y%m%dT%H%M%SZ'))/'scene.json'
    while not supplement.exists():
        if time.monotonic()-began>7200:raise TimeoutError('Actual3.9um source not ready')
        time.sleep(5)
    sw_meta=read_manifest(supplement);lw_meta=read_manifest(Path(m['source_manifest']))
    files=[p for p in lw_meta['local_files'] if '_B13_' in Path(p).name and any(f'_S{i:02d}10.' in Path(p).name for i in [3,4,5])]+sw_meta['local_files']
    pair={'satellite':'himawari8','local_files':files}
    scene,bands,start,end,policies=calibrated_pair(pair);area=scene['B13'].attrs['area']
    r0,r1,c0,c1=m['lowcloud_restoration']['roi_native_yx'];y0,y1,x0,x1=SLICE
    t,sw=[np.ma.filled(scene[band].isel(y=slice(r0,r1),x=slice(c0,c1)).compute(scheduler='single-threaded').data,np.nan).astype(np.float32) for band in bands]
    with np.load(root/'lowcloud_evidence_v4.npz') as evidence:
        low=evidence['low_confidence'].copy();raw_p=evidence['cloud_probability'].copy()
    # Source identity is carried by the verified phase pass, not guessed from
    # the HSD manifest. This pass cannot issue new raw-range requests.
    record=next(r for r in m['lowcloud_restoration']['sources'] if r['key'].endswith('_CLOUD_MASK_EN.nc'))
    with RangeArchive(Offline(),'noaa-himawari8',record['key'],record['remote_bytes'],record['etag'],Path(record['archive']),cfg,max_bytes=0,block_size=65536) as stream:
        with h5py.File(stream,'r') as f:
            mask=decode(f['CloudMask'],np.s_[r0:r1,c0:c1],stream)
            q=decode(f['CloudMaskQualFlag'],np.s_[r0:r1,c0:c1],stream)
    yy,xx=np.indices(t.shape);edge=np.minimum.reduce([yy+1,xx+1,t.shape[0]-yy,t.shape[1]-xx])
    blend=np.clip(edge/16,0,1);blend=blend*blend*(3-2*blend)
    good=np.isfinite(raw_p)&(raw_p>=0)&(raw_p<=1)&(q==0)&np.isin(mask,[0,1,2,3])
    p=np.where(good,(np.isin(mask,[2,3])&(q==0))*(1-blend)+raw_p*blend,0).astype(np.float32)
    softened_low=low*inward_feather(low>0)
    old=np.asarray(Image.open(root/'cloud_lowcloud_v4.png').convert('RGBA')).copy();result=old.copy();eligible_count=0;pair_count=0
    for row in range(0,r1-r0,128):
        last=min(row+128,r1-r0);sl=np.s_[(r0-y0+row)*2:(r0-y0+last)*2,(c0-x0)*2:(c1-x0)*2]
        lo,la=area.get_lonlat_from_array_coordinates(*np.meshgrid(np.arange(c0,c1),np.arange(r0+row,r0+last)))
        geo=np.isfinite(lo)&np.isfinite(la)
        safe_lo=np.where(geo,lo,0);safe_la=np.where(geo,la,0)
        elevation=solar_weights(stamp,safe_lo,safe_la).elevation_deg
        first=solar_weights(utc_time(start),safe_lo,safe_la).elevation_deg;final=solar_weights(utc_time(end),safe_lo,safe_la).elevation_deg
        night=(first<=-6)&(final<=-6)&geo
        eligible_count+=int(night.sum());pair_count+=int((night&np.isfinite(sw[row:last])&(sw[row:last]>=100)&(sw[row:last]<=350)).sum())
        old_rgb,old_alpha=night_material(t[row:last],p[row:last],low[row:last])
        new_rgb,new_alpha=spectral_night_material(t[row:last],sw[row:last],p[row:last],softened_low[row:last],night)
        expand=lambda v:np.repeat(np.repeat(v,2,0),2,1)
        old_rgb,old_alpha,new_rgb,new_alpha=[expand(v) for v in (old_rgb,old_alpha,new_rgb,new_alpha)]
        a=np.clip(np.sin(np.deg2rad(expand(elevation)))/.25,0,1);day=a*a*a*(a*(a*6-15)+10)
        if m['vis'] is None:day[:]=0
        block=old[sl];alpha=block[...,3].astype(np.float32)/255
        va=np.maximum(alpha-old_alpha*(1-day),0)
        vp=np.maximum(block[...,:3].astype(np.float32)/255*alpha[...,None]-old_rgb*(old_alpha*(1-day))[...,None],0)
        total=va+new_alpha*(1-day)
        rgb=np.divide(vp+new_rgb*(new_alpha*(1-day))[...,None],total[...,None],out=np.zeros_like(vp),where=total[...,None]>0)
        result[sl][...,:3]=np.rint(np.clip(rgb,0,1)*255).astype(np.uint8);result[sl][...,3]=np.rint(np.clip(total,0,1)*255).astype(np.uint8)
        result[sl][day>=1]=block[day>=1]
    target=root/'cloud_spectral_v5.png';tmp=root/'cloud_spectral_v5.tmp.png';Image.fromarray(result).save(tmp,compress_level=3);tmp.replace(target)
    m['material_revision']=5;m['render_material_file']=target.name
    m['spectral_restoration']={'shortwave_used':True,'source_manifest':str(supplement.resolve()),'band_policies':policies,'actual_pair_interval_utc':[start,end],
        'night_eligible_native_pixels':eligible_count,'paired_night_native_pixels':pair_count,
        'classification':'unchanged phase/height/error evidence; LW-SW is texture only, not a cloud-type detector',
        'tint_edge':'inward2 native-pixel confidence feather only; no spatial RGB blur or support expansion',
        'fully_selected_vis_pixels_unchanged':True,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    tmp=meta_path.with_suffix('.tmp');tmp.write_text(json.dumps(m,indent=2),encoding='utf-8');tmp.replace(meta_path)
    print('SPECTRAL',m['nominal_utc'],'night pairs',pair_count,flush=True);return m


if __name__=='__main__':
    folder=load_config().processed_dir/'goni_film_v1';items=json.loads((folder/'inventory.json').read_text())['scenes']
    items=sorted(items,key=lambda m:({'2020-10-30T14:00:00+00:00':0,'2020-10-30T09:00:00+00:00':1}.get(m['nominal_utc'],2),m['nominal_utc']))
    with ProcessPoolExecutor(max_workers=2) as pool:frames=list(pool.map(restore,items))
    (folder/'frames_spectral_v5.json').write_text(json.dumps(frames,indent=2),encoding='utf-8');print('SPECTRAL READY31',flush=True)
