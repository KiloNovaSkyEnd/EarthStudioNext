"""Recover cold-core night texture from original B13, not from clipped PNGs."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from PIL import Image
from ges.storage import load_config
from ges.render import create_satpy_scene
from ges.download import read_manifest
from ges.goni_data import SLICE
from ges.catalog import utc_time
from ges.solar import solar_weights


def refine(item):
    cfg=load_config();stamp=utc_time(item['nominal_utc']);folder=cfg.processed_dir/'goni_film_v1/frames'/stamp.strftime('%Y%m%dT%H%MZ')
    p=folder/'frame.json';started=time.monotonic()
    while not p.exists():
        if time.monotonic()-started>7200:raise TimeoutError('Source acquisition not ready')
        time.sleep(5)
    m=json.loads(p.read_text())
    if m.get('material_revision',0)>=2:return m
    raw=read_manifest(Path(m['source_manifest']));files=[f for f in raw['local_files'] if '_B13_' in Path(f).name]
    s=create_satpy_scene(files,'himawari8');s.load(['B13']);area=s['B13'].attrs['area'];y0,y1,x0,x1=SLICE
    t=np.ma.filled(s['B13'].isel(y=slice(y0,y1),x=slice(x0,x1)).compute(scheduler='single-threaded').data,np.nan).astype(np.float32)
    valid=np.isfinite(t)&(t>=100)&(t<=350)
    path=folder/'cloud.png';old=np.asarray(Image.open(path).convert('RGBA')).copy();result=np.empty_like(old)
    for row in range(0,y1-y0,128):
        end=min(row+128,y1-y0);sl=slice(row*2,end*2);block=old[sl];alpha=block[...,3].astype(np.float32)/255
        lo,la=area.get_lonlat_from_array_coordinates(*np.meshgrid(np.arange(x0,x1),np.arange(y0+row,y0+end)))
        geo=np.isfinite(lo)&np.isfinite(la);e=solar_weights(stamp,np.where(geo,lo,0),np.where(geo,la,0)).elevation_deg
        e=np.repeat(np.repeat(e,2,0),2,1);a=np.clip(np.sin(np.deg2rad(e))/.25,0,1);day=a*a*a*(a*(a*6-15)+10)
        if m['vis'] is None:day[:]=0
        temp=np.repeat(np.repeat(t[row:end],2,0),2,1);support=(alpha>0)&np.repeat(np.repeat(valid[row:end],2,0),2,1)
        cold_old=np.clip((300-np.where(support,temp,300))/100,0,1)
        old_ir_a=(.20+.78*cold_old**.8)*support;old_ir_c=.42+.43*cold_old
        cold=np.clip((300-np.where(support,temp,300))/130,0,1)
        new_ir_a=(.08+.90*cold**1.15)*support;new_ir_c=.42+.43*cold
        # Remove only the old IR contribution and replace with original-B13
        # display transfer. Real daytime VIS and masks are not regenerated.
        va=np.maximum(alpha-old_ir_a*(1-day),0)
        old_premult=block[...,:3].astype(np.float32)/255*alpha[...,None]
        vp=np.maximum(old_premult-(old_ir_a*old_ir_c*(1-day))[...,None],0)
        new_a=va+new_ir_a*(1-day)
        color=np.divide(vp+(new_ir_a*new_ir_c*(1-day))[...,None],new_a[...,None],out=np.zeros_like(vp),where=new_a[...,None]>0)
        result[sl,...,:3]=np.rint(np.clip(color,0,1)*255).astype(np.uint8)
        result[sl,...,3]=np.rint(np.clip(new_a,0,1)*255).astype(np.uint8)
        result[sl][day>=1]=block[day>=1]
    original=folder/'cloud_initial.png'
    if not original.exists():path.replace(original)
    temporary=folder/'cloud_refined.png';Image.fromarray(result).save(temporary);temporary.replace(path)
    cloud_support=old[::2,::2,3]>0;clipped=valid&cloud_support&(t<200)
    m['material_revision']=2
    m['ir_display_refinement']={'source_band':'B13','units':'K','old_saturated_below_k':200,
        'new_white_endpoint_k':170,'new_alpha':'0.08+0.90*cold^1.15; cold=clip((300-T)/130,0,1)',
        'clipped_cold_core_native_pixels':int(clipped.sum()),'cold_core_original_std_k':float(t[clipped].std()) if clipped.any() else 0,
        'initial_png_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'refined_png_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'fully_selected_vis_pixels_unchanged':True,'observation_coverage_and_measured_height_unchanged':True}
    temporary=p.with_suffix('.tmp');temporary.write_text(json.dumps(m,indent=2),encoding='utf-8');temporary.replace(p)
    print('REFINED',stamp.isoformat(),'cold pixels',int(clipped.sum()),'original BT std K',round(m['ir_display_refinement']['cold_core_original_std_k'],3),flush=True)
    return m


if __name__=='__main__':
    folder=load_config().processed_dir/'goni_film_v1';inventory=json.loads((folder/'inventory.json').read_text())
    with ProcessPoolExecutor(max_workers=2) as pool:frames=list(pool.map(refine,inventory['scenes']))
    (folder/'frames_refined.json').write_text(json.dumps(frames,indent=2),encoding='utf-8');print('REFINED READY',len(frames),flush=True)
