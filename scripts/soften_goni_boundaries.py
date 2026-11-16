"""Inward alpha antialias and continuous IR display; never extend cloud support."""
from pathlib import Path
import hashlib
import json
import time
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from ges.storage import load_config
from ges.render import create_satpy_scene
from ges.download import read_manifest
from ges.goni_data import SLICE
from ges.catalog import utc_time
from ges.solar import solar_weights


def inward_feather(support):
    """Two native-pixel inward transition. Clear/missing stays exactly zero."""
    distance=distance_transform_edt(np.pad(np.asarray(support,bool),1))[1:-1,1:-1]
    t=np.clip(distance/2,0,1)
    return (t*t*(3-2*t)).astype(np.float32)


def main():
    folder=load_config().processed_dir/'goni_film_v1'
    inventory=json.loads((folder/'inventory.json').read_text())
    for item in inventory['scenes']:
        stamp=utc_time(item['nominal_utc']);root=folder/'frames'/stamp.strftime('%Y%m%dT%H%MZ');p=root/'frame.json'
        began=time.monotonic()
        while True:
            try:m=json.loads(p.read_text())
            except (FileNotFoundError,json.JSONDecodeError):m={}
            if m.get('material_revision',0)>=2:break
            if time.monotonic()-began>7200:raise TimeoutError('Refined observation not ready')
            time.sleep(5)
        if m.get('material_revision',0)>=3:continue
        raw=read_manifest(Path(m['source_manifest']))
        scene=create_satpy_scene([f for f in raw['local_files'] if '_B13_' in Path(f).name],'himawari8');scene.load(['B13'])
        area=scene['B13'].attrs['area'];y0,y1,x0,x1=SLICE
        temp=np.ma.filled(scene['B13'].isel(y=slice(y0,y1),x=slice(x0,x1)).compute(scheduler='single-threaded').data,np.nan).astype(np.float32)
        old=np.asarray(Image.open(root/'cloud.png').convert('RGBA')).copy();result=np.empty_like(old)
        support=old[::2,::2,3]>0
        edge=inward_feather(support)
        for row in range(0,y1-y0,128):
            end=min(row+128,y1-y0);sl=slice(row*2,end*2);block=old[sl];alpha=block[...,3].astype(np.float32)/255
            lo,la=area.get_lonlat_from_array_coordinates(*np.meshgrid(np.arange(x0,x1),np.arange(y0+row,y0+end)))
            valid_geo=np.isfinite(lo)&np.isfinite(la)
            elev=solar_weights(stamp,np.where(valid_geo,lo,0),np.where(valid_geo,la,0)).elevation_deg
            a=np.clip(np.sin(np.deg2rad(elev))/.25,0,1);day=a*a*a*(a*(a*6-15)+10)
            if m['vis'] is None:day[:]=0
            day=np.repeat(np.repeat(day,2,0),2,1)
            t=np.repeat(np.repeat(temp[row:end],2,0),2,1)
            valid=(alpha>0)&np.isfinite(t)&(t>=100)&(t<=350)
            cold=np.clip((300-np.where(valid,t,300))/130,0,1)
            previous=(.08+.90*cold**1.15)*valid
            replacement=.98*cold**1.6*valid
            color=.42+.43*cold
            vis_alpha=np.maximum(alpha-previous*(1-day),0)
            vis_premult=np.maximum(block[...,:3].astype(np.float32)/255*alpha[...,None]-(previous*color*(1-day))[...,None],0)
            total=vis_alpha+replacement*(1-day)
            rgb=np.divide(vis_premult+(replacement*color*(1-day))[...,None],total[...,None],out=np.zeros_like(vis_premult),where=total[...,None]>0)
            feather=np.repeat(np.repeat(edge[row:end],2,0),2,1)
            result[sl,...,:3]=np.rint(np.clip(rgb,0,1)*255).astype(np.uint8)
            result[sl,...,3]=np.rint(np.clip(total*feather,0,1)*255).astype(np.uint8)
            result[sl][alpha==0]=block[alpha==0]
        backup=root/'cloud_revision2.png'
        if not backup.exists():(root/'cloud.png').replace(backup)
        temporary=root/'cloud_softened.png';Image.fromarray(result).save(temporary);temporary.replace(root/'cloud.png')
        assert not np.any((old[...,3]==0)&(result[...,3]>0))
        m['material_revision']=3
        m['boundary_display']={'method':'2 native IR pixels inward smoothstep alpha only; RGB not spatially mixed; no support extension',
            'native_edge_pixels':int(((edge>0)&(edge<1)).sum()),'ir_alpha':'.98*clip((300-T)/130,0,1)^1.6; no opacity floor',
            'previous_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'new_sha256':hashlib.sha256((root/'cloud.png').read_bytes()).hexdigest(),
            'missing_observations_filled':False,'classification_changed':False}
        temporary=p.with_suffix('.tmp');temporary.write_text(json.dumps(m,indent=2),encoding='utf-8');temporary.replace(p)
        print('SOFTENED',m['nominal_utc'],'native edge pixels',m['boundary_display']['native_edge_pixels'],flush=True)
    print('BOUNDARY READY31',flush=True)


if __name__=='__main__':main()
