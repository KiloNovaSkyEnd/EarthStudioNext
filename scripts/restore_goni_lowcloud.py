"""Restore phase/height-screened night low clouds and delivered cloud confidence.

All new raw ranges share the original aggregate5GB ceiling. Confidence/phase
ROI is explicit, and does not turn unclassified outside pixels into low clouds.
"""
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import hashlib
import json
from multiprocessing import Manager
from pathlib import Path
import h5py
import numpy as np
from PIL import Image
from ges.catalog import s3_client,utc_time
from ges.download import read_manifest
from ges.goni_data import SLICE,decode
from ges.goni_lowcloud import low_liquid_confidence,night_material
from ges.range_archive import RangeArchive,configure_group_budget
from ges.render import create_satpy_scene
from ges.solar import solar_weights
from ges.storage import load_config

ROI=(1200,2600,1600,3400)


def catalog(item):
    stamp=utc_time(item['nominal_utc']);s3=s3_client()
    response=s3.list_objects_v2(Bucket='noaa-himawari8',Prefix=stamp.strftime('AHI-L2-FLDK-Clouds/%Y/%m/%d/%H%M/'))
    found=[v for v in response.get('Contents',[]) if v['Key'].endswith('_CLOUD_PHASE_EN.nc')]
    if len(found)!=1:raise ValueError('Exactly one matching actual phase product required')
    v=found[0];return {**item,'phase':{'kind':'PHASE','key':v['Key'],'size':v['Size'],'etag':v['ETag']}}


def restore(item):
    cfg=load_config();stamp=utc_time(item['nominal_utc']);root=cfg.processed_dir/'goni_film_v1/frames'/stamp.strftime('%Y%m%dT%H%MZ')
    meta_path=root/'frame.json';m=json.loads(meta_path.read_text())
    if m.get('material_revision',0)>=4 and m['lowcloud_restoration']['roi_native_yx']==list(ROI):return m
    raw=read_manifest(Path(m['source_manifest']));scene=create_satpy_scene(raw['local_files'],'himawari8');scene.load(['B13'])
    area=scene['B13'].attrs['area'];y0,y1,x0,x1=SLICE;r0,r1,c0,c1=ROI
    full=np.s_[y0:y1,x0:x1];inner=np.s_[r0:r1,c0:c1];local=np.s_[r0-y0:r1-y0,c0-x0:c1-x0]
    fields={};audits=[]
    for record in [*item['support'],item['phase']]:
        kind=record['kind'];archive=cfg.raw_dir/'goni_l2_ranges'/stamp.strftime('%Y%m%dT%H%MZ')/(kind+'_64k')
        # Existing height/mask fields reuse archived bytes; only regional
        # confidence/phase arrays are new. Aggregate manager is authoritative.
        stream=RangeArchive(s3_client(),'noaa-himawari8',record['key'],record['size'],record['etag'],archive,cfg,max_bytes=9_000_000,block_size=65536)
        with stream:
            with h5py.File(stream,'r') as f:
                def scalar(name):return np.asarray(f.attrs[name]).ravel()[0]
                image_time=scalar('Image_Time');image_time=image_time.decode() if isinstance(image_time,bytes) else str(image_time)
                actual=datetime.strptime(str(int(scalar('Image_Date')))+image_time,'%Y%j%H%M_%S').replace(tzinfo=timezone.utc)
                if not stamp<=actual<stamp+timedelta(minutes=1):raise ValueError('Mismatched actual phase/mask/height scan')
                if int(np.asarray(f['granule_level_quality_flag'][()]).ravel()[0])!=0:raise ValueError('Degraded actual granule')
                if kind=='MASK':
                    for name in ['CloudMask','CloudMaskQualFlag']:fields[name]=decode(f[name],full,stream)
                    fields['CloudProbability']=decode(f['CloudProbability'],inner,stream)
                elif kind=='HEIGHT':
                    # These chunks were archived for the previous top-height
                    # product. Exact raw retrieval/error, not display height.
                    for name in ['CldTopHght','ZcError','CloudHgtQF']:
                        fields[name]=decode(f[name],inner,stream)
                else:
                    fields['CloudPhase']=decode(f['CloudPhase'],inner,stream)
                    fields['CloudPhaseFlag']=decode(f['CloudPhaseFlag'],np.s_[r0:r1,c0:c1,0],stream)
                    errors=[]
                    for x,y in [(1800,1400),(3000,2300)]:
                        lo,la=area.get_lonlat_from_array_coordinates(x,y)
                        errors.append(max(abs((float(f['Longitude'][y,x])-lo+180)%360-180),abs(float(f['Latitude'][y,x])-la)))
                    if max(errors)>.002:raise ValueError('Phase navigation differs from actual IR grid')
                audits.append({**stream.audit(),'image_time_utc':actual.isoformat()})
    mask=fields['CloudMask'];mq=fields['CloudMaskQualFlag']
    probability=(np.isin(mask,[2,3])&(mq==0)).astype(np.float32)
    native_p=fields['CloudProbability'];good=np.isfinite(native_p)&(native_p>=0)&(native_p<=1)&(mq[local]==0)&np.isin(mask[local],[0,1,2,3])
    # Continuous delivered probability replaces the old binary mask only in
    # the documented ROI. Blend its display transfer inward at ROI edges.
    yy,xx=np.indices(native_p.shape);edge=np.minimum.reduce([yy+1,xx+1,native_p.shape[0]-yy,native_p.shape[1]-xx])
    blend=np.clip(edge/16,0,1).astype(np.float32);blend=blend*blend*(3-2*blend)
    probability[local]=np.where(good,probability[local]*(1-blend)+native_p*blend,0)
    low=np.zeros_like(probability)
    low[local]=low_liquid_confidence(mask[local],mq[local],fields['CloudPhase'],fields['CloudPhaseFlag'],
                                      fields['CldTopHght']/1000,fields['ZcError']/1000,fields['CloudHgtQF'])*blend
    t=np.ma.filled(scene['B13'].isel(y=slice(r0,r1),x=slice(c0,c1)).compute(scheduler='single-threaded').data,np.nan).astype(np.float32)
    v=None
    if m['vis'] is not None:
        scene.load(['B03']);vis=scene['B03'];va=vis.attrs['area']
        if vis.shape!=(22000,22000) or va.crs!=area.crs or not np.allclose(va.area_extent,area.area_extent,atol=.1):raise ValueError('VIS and IR footprints differ')
        source=vis.data[r0*4:r1*4,c0*4:c1*4].astype(np.float32)
        v=np.ma.filled(source.reshape(((r1-r0)*2,2,(c1-c0)*2,2)).mean(axis=(1,3),dtype=np.float32).compute(scheduler='single-threaded'),np.nan).astype(np.float32)/100
    base=root/'cloud_revision2.png'
    if not base.exists():base=root/'cloud.png'
    rgba=np.asarray(Image.open(base).convert('RGBA')).copy()
    for row in range(r0,r1,128):
        end=min(row+128,r1);sl=slice((row-r0)*2,(end-r0)*2)
        out_y=slice((row-y0)*2,(end-y0)*2);out_x=slice((c0-x0)*2,(c1-x0)*2)
        native_y=slice(row-y0,end-y0);native_x=slice(c0-x0,c1-x0)
        lo,la=area.get_lonlat_from_array_coordinates(*np.meshgrid(np.arange(c0,c1),np.arange(row,end)))
        geo=np.isfinite(lo)&np.isfinite(la)
        elevation=solar_weights(stamp,np.where(geo,lo,0),np.where(geo,la,0)).elevation_deg
        p=probability[native_y,native_x]*geo
        n_rgb,n_alpha=night_material(t[row-r0:end-r0],p,low[native_y,native_x])
        expand=lambda a:np.repeat(np.repeat(a,2,0),2,1)
        n_rgb,n_alpha=expand(n_rgb),expand(n_alpha);elevation=expand(elevation)
        a=np.clip(np.sin(np.deg2rad(elevation))/.25,0,1);day=a*a*a*(a*(a*6-15)+10)
        if v is None:day[:]=0
        if v is not None:
            safe=np.maximum(np.sin(np.deg2rad(elevation)),np.sin(np.deg2rad(6)))
            refl=np.where(np.isfinite(v[sl])&(elevation>0),np.clip(v[sl]/safe,0,1.2),0)
            d_alpha=np.clip(refl/1.05,0,1)**.8*expand(p)
            d_rgb=np.clip(.55+.45*np.sqrt(np.clip(refl,0,1)),0,1)[...,None]
        else:d_alpha=np.zeros_like(day);d_rgb=np.zeros(day.shape+(1,),np.float32)
        alpha=d_alpha*day+n_alpha*(1-day)
        premult=d_rgb*(d_alpha*day)[...,None]+n_rgb*(n_alpha*(1-day))[...,None]
        rgb=np.divide(premult,alpha[...,None],out=np.zeros_like(premult),where=alpha[...,None]>0)
        rgba[out_y,out_x,:3]=np.rint(np.clip(rgb,0,1)*255).astype(np.uint8)
        rgba[out_y,out_x,3]=np.rint(np.clip(alpha,0,1)*255).astype(np.uint8)
    target=root/'cloud_lowcloud_v4.png';temporary=root/'cloud_lowcloud_v4.tmp.png'
    Image.fromarray(rgba).save(temporary,compress_level=3);temporary.replace(target)
    np.savez_compressed(root/'lowcloud_evidence_v4.npz',low_confidence=low[local],cloud_probability=native_p,
                        cloud_phase=fields['CloudPhase'],phase_quality=fields['CloudPhaseFlag'],
                        height_km=fields['CldTopHght']/1000,height_error_km=fields['ZcError']/1000,native_slice_yx=np.array(ROI))
    m['material_revision']=4;m['render_material_file']=target.name
    m['lowcloud_restoration']={'roi_native_yx':list(ROI),'strict_low_pixels':int((low>=.999).sum()),'nominal_uncertain_low_pixels':int(((low>0)&(low<.999)).sum()),
        'policy':'mask2/3 QF0, liquid/supercooled phase1/2 QF0, heightQF0, height>0 and error0..3km; strict height+error<=3km; nominal height<=3km gets35% tint',
        'alpha_policy':'Delivered continuous CloudProbability inside ROI, smoothly16pixels joined to binary mask outside; classification never gates other cloud alpha',
        'night_texture':'measured B13 thermal response; B07 not acquired, no spectral-pair texture claim',
        'outside_roi':'revision2 measured VIS/IR retained; no phase-confirmed blue or continuous-probability claim outside ROI',
        'blue_is_display_tint_not_observed_visible_color':True,'new_blue_classification_outside_roi':False,
        'new_radiance_measurements_generated':False,'sources':audits,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    temporary=meta_path.with_suffix('.tmp');temporary.write_text(json.dumps(m,indent=2),encoding='utf-8');temporary.replace(meta_path)
    print('RESTORED',m['nominal_utc'],'strict low',m['lowcloud_restoration']['strict_low_pixels'],'newMB',round(sum(a['new_bytes_this_run'] for a in audits)/1e6,2),flush=True)
    return m


def main():
    cfg=load_config();folder=cfg.processed_dir/'goni_film_v1';inventory=json.loads((folder/'inventory.json').read_text());index=folder/'lowcloud_inventory.json'
    if index.exists():items=json.loads(index.read_text())
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:items=list(pool.map(catalog,inventory['scenes']))
        index.write_text(json.dumps(items,indent=2),encoding='utf-8')
    used=sum(p.stat().st_size for p in (cfg.raw_dir/'goni_l2_ranges').rglob('*.bin'))
    limit=int(cfg.max_single_scene_gb*1e9)-inventory['hsd_total_bytes']
    print('SHARED RAW',used,'/',limit,'remaining',limit-used,flush=True)
    with Manager() as manager:
        counter=manager.Value('q',used);lock=manager.Lock()
        with ProcessPoolExecutor(max_workers=2,initializer=configure_group_budget,initargs=(counter,lock,limit)) as pool:
            ordered=sorted(items,key=lambda m: ({'2020-10-30T14:00:00+00:00':0,'2020-10-30T09:00:00+00:00':1,'2020-10-30T04:00:00+00:00':2}.get(m['nominal_utc'],3),m['nominal_utc']))
            frames=list(pool.map(restore,ordered))
        print('FINAL RAW',inventory['hsd_total_bytes']+counter.value,flush=True)
    (folder/'frames_lowcloud_v4.json').write_text(json.dumps(frames,indent=2),encoding='utf-8')


if __name__=='__main__':main()
