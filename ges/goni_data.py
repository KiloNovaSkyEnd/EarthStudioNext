"""Native AHI regional material for real Goni acquisitions, with L2 uncertainty."""
from datetime import datetime,timezone,timedelta
import gc
import json
from pathlib import Path
import numpy as np
from PIL import Image
from .range_archive import RangeArchive
from .catalog import utc_time,s3_client
from .download import read_manifest
from .storage import load_config
from .render import create_satpy_scene,observation_interval
from .solar import solar_weights

SLICE=(600,3300,700,4400)


def refine_ir_material(block,temperature,elevation,has_vis=True):
    """Recover night cold-core tonal differences from original BT, not old PNG."""
    block=np.asarray(block);temperature=np.asarray(temperature,np.float32);elevation=np.asarray(elevation,np.float32)
    if block.shape!=temperature.shape+(4,) or temperature.shape!=elevation.shape:raise ValueError('Matching RGBA, Kelvin and solar grids required')
    alpha=block[...,3].astype(np.float32)/255
    a=np.clip(np.sin(np.deg2rad(elevation))/.25,0,1);day=a*a*a*(a*(a*6-15)+10)
    if not has_vis:day[:]=0
    support=(alpha>0)&np.isfinite(temperature)&(temperature>=100)&(temperature<=350)
    old_cold=np.clip((300-np.where(support,temperature,300))/100,0,1)
    old_a=(.20+.78*old_cold**.8)*support;old_c=.42+.43*old_cold
    cold=np.clip((300-np.where(support,temperature,300))/130,0,1)
    new_a=(.08+.90*cold**1.15)*support;new_c=.42+.43*cold
    va=np.maximum(alpha-old_a*(1-day),0)
    vp=np.maximum(block[...,:3].astype(np.float32)/255*alpha[...,None]-(old_a*old_c*(1-day))[...,None],0)
    total=va+new_a*(1-day)
    color=np.divide(vp+(new_a*new_c*(1-day))[...,None],total[...,None],out=np.zeros_like(vp),where=total[...,None]>0)
    result=np.dstack([np.rint(np.clip(color,0,1)*255).astype(np.uint8),np.rint(np.clip(total,0,1)*255).astype(np.uint8)])
    result[day>=1]=block[day>=1]
    return result


def decode(variable,selection,archive=None):
    if archive is not None:archive.prefetch_variable(variable,selection)
    values=np.asarray(variable[selection],np.float32)
    fill=np.asarray(variable.attrs.get('_FillValue',np.nan)).ravel()[0]
    valid=np.isfinite(values)&(values!=fill)
    if 'valid_range' in variable.attrs:
        low,high=variable.attrs['valid_range'];valid&=(values>=low)&(values<=high)
    scale=np.asarray(variable.attrs.get('scale_factor',1.)).ravel()[0]
    offset=np.asarray(variable.attrs.get('add_offset',0.)).ravel()[0]
    return np.where(valid,values*scale+offset,np.nan).astype(np.float32)


def support_fields(item,area):
    import h5py
    cfg=load_config();s3=s3_client();y0,y1,x0,x1=SLICE;sl=np.s_[y0:y1,x0:x1]
    fields={};records=[];image_times=[]
    for record in item['support']:
        kind=record['kind'];names=['CloudMask','CloudMaskQualFlag'] if kind=='MASK' else ['CldTopHght','ZcError','CloudHgtQF']
        cap=16_000_000 if kind=='MASK' else 70_000_000
        archive=cfg.raw_dir/'goni_l2_ranges'/utc_time(item['nominal_utc']).strftime('%Y%m%dT%H%MZ')/(kind+'_64k')
        raw=RangeArchive(s3,'noaa-himawari8',record['key'],record['size'],record['etag'],archive,cfg,max_bytes=cap,block_size=65536)
        with raw:
            with h5py.File(raw,'r') as d:
                def scalar(name):return np.asarray(d.attrs[name]).ravel()[0]
                stamp=datetime.strptime(str(int(scalar('Image_Date')))+str(scalar('Image_Time').decode() if isinstance(scalar('Image_Time'),bytes) else scalar('Image_Time')),'%Y%j%H%M_%S').replace(tzinfo=timezone.utc)
                nominal=utc_time(item['nominal_utc'])
                if not nominal<=stamp<nominal+timedelta(minutes=1):raise ValueError('L2 image time is not requested HSD scan')
                image_times.append(stamp.isoformat())
                if int(np.asarray(d['granule_level_quality_flag'][()]).ravel()[0])!=0:raise ValueError('Degraded L2 granule')
                for name in names:
                    if d[name].shape!=(5500,5500):raise ValueError('L2 source grid changed')
                    if name in ['CldTopHght','ZcError'] and d[name].attrs['units'].decode()!='Meter':raise ValueError('Cloud height/error must be metres')
                    if kind=='HEIGHT':
                        # Heights cover the storm/nearby Asia. Preserve NaN
                        # outside this smaller verified subset, never reuse a
                        # nearby height to make the whole cloud map complete.
                        inner=np.s_[1000:3000,1100:4100]
                        values=decode(d[name],inner,raw)
                        fields[name]=np.full((y1-y0,x1-x0),np.nan,np.float32)
                        fields[name][1000-y0:3000-y0,1100-x0:4100-x0]=values
                    else:fields[name]=decode(d[name],sl,raw)
                nav=[]
                for x,y in [(1300,1100),(2600,2200),(4100,2600)]:
                    lo,la=area.get_lonlat_from_array_coordinates(x,y)
                    a,b=float(d['Longitude'][y,x]),float(d['Latitude'][y,x])
                    error=max(abs((a-lo+180)%360-180),abs(b-la));nav.append(error)
                if max(nav)>.002:raise ValueError('L2 embedded navigation differs from actual HSD grid')
                records.append({**raw.audit(),'image_time_utc':stamp.isoformat(),'fields':names,'navigation_max_error_deg':max(nav)})
    if len(set(image_times))!=1:raise ValueError('L2 mask/height times differ')
    cloudy=np.isin(fields['CloudMask'],[2,3])&(fields['CloudMaskQualFlag']==0)
    h=fields['CldTopHght'];err=fields['ZcError']
    valid=cloudy&(fields['CloudHgtQF']==0)&np.isfinite(h)&(h>0)&(h<=20000)&np.isfinite(err)&(err>=0)&(err<=3000)
    return cloudy,np.where(valid,h/1000,np.nan).astype(np.float32),records


def prepare_frame(item):
    cfg=load_config();stamp=utc_time(item['nominal_utc']);dest=cfg.processed_dir/'goni_film_v1/frames'/stamp.strftime('%Y%m%dT%H%MZ')
    output=dest/'frame.json'
    if output.exists():return json.loads(output.read_text())
    dest.mkdir(parents=True,exist_ok=True);raw=read_manifest(Path(item['manifest']))
    scene=create_satpy_scene(raw['local_files'],'himawari8');scene.load(['B13']);ir=scene['B13'];area=ir.attrs['area']
    if ir.shape!=(5500,5500) or ir.attrs['units']!='K' or abs(ir.attrs['wavelength'].central-10.4)>.1:
        raise ValueError('Actual 2km AHI B13 calibrated grid required')
    start,end=observation_interval(ir.attrs);cloudy,height,records=support_fields(item,area)
    y0,y1,x0,x1=SLICE
    t=np.ma.filled(ir.isel(y=slice(y0,y1),x=slice(x0,x1)).compute(scheduler='single-threaded').data,np.nan).astype(np.float32)
    valid=np.isfinite(t)&(t>=100)&(t<=350)
    lon,lat=area.get_lonlat_from_array_coordinates(*np.meshgrid(np.arange(x0,x1),np.arange(y0,y1)))
    geographic=np.isfinite(lon)&np.isfinite(lat)
    sun=solar_weights(stamp,np.where(geographic,lon,0),np.where(geographic,lat,0));e=sun.elevation_deg
    cold=np.clip((300-np.where(valid,t,300))/100,0,1)
    # Neutral observed IR display. These are artistic alpha/grey values,
    # not retrieved visible imagery or optical thickness.
    na=(.20+.78*cold**.8)*cloudy*valid
    nrgb=.42+.43*cold
    da=np.zeros_like(t);drgb=np.zeros_like(t);vis_record=None
    if any('_B03_' in p for p in raw['local_files']):
        scene.load(['B03']);vis=scene['B03'];va=vis.attrs['area']
        if vis.shape!=(22000,22000) or vis.attrs['units']!='%' or va.crs!=area.crs or not np.allclose(va.area_extent,area.area_extent,atol=.1):
            raise ValueError('Verified 500m VIS and 2km IR footprints required')
        # Average measured500m samples conservatively to1km, not a global map.
        source=vis.data[y0*4:y1*4,x0*4:x1*4].astype(np.float32)
        v=source.reshape(((y1-y0)*2,2,(x1-x0)*2,2)).mean(axis=(1,3),dtype=np.float32).compute(scheduler='single-threaded')
        v=np.ma.filled(v,np.nan).astype(np.float32)/100
        elev=np.repeat(np.repeat(e,2,0),2,1);mask=np.repeat(np.repeat(cloudy,2,0),2,1)
        safe=np.maximum(np.sin(np.deg2rad(elev)),np.sin(np.deg2rad(6)))
        refl=np.where(np.isfinite(v)&(elev>0)&mask,np.clip(v/safe,0,1.2),0)
        da=np.clip(refl/1.05,0,1)**.8
        drgb=np.clip(.55+.45*np.sqrt(np.clip(refl,0,1)),0,1)
        vis_record={'band':'B03','original_resolution_m':500,'display_resolution_m':1000,'scan_utc':observation_interval(vis.attrs)}
    else:
        da=np.repeat(np.repeat(da,2,0),2,1);drgb=np.repeat(np.repeat(drgb,2,0),2,1)
        elev=np.repeat(np.repeat(e,2,0),2,1)
    nalpha=np.repeat(np.repeat(na,2,0),2,1);ncolor=np.repeat(np.repeat(nrgb,2,0),2,1)
    # Global smooth solar transition, selected only when this scan has VIS.
    a=np.clip((np.sin(np.deg2rad(elev))-.0)/.25,0,1);day=a*a*a*(a*(a*6-15)+10)
    if vis_record is None:day[:]=0
    alpha=da*day+nalpha*(1-day)
    rgb=np.divide(drgb*da*day+ncolor*nalpha*(1-day),alpha,out=np.zeros_like(alpha),where=alpha>0)
    rgba=np.empty(alpha.shape+(4,),np.uint8)
    for k in range(3):rgba[...,k]=np.rint(np.clip(rgb,0,1)*255).astype(np.uint8)
    rgba[...,3]=np.rint(np.clip(alpha,0,1)*255).astype(np.uint8)
    Image.fromarray(rgba).save(dest/'cloud.png');Image.fromarray(valid.astype(np.uint8)*255).save(dest/'ir_coverage.png')
    np.savez_compressed(dest/'height.npz',height_km=height)
    px=(area.area_extent[2]-area.area_extent[0])/5500;py=(area.area_extent[3]-area.area_extent[1])/5500
    extent=[area.area_extent[0]+x0*px,area.area_extent[3]-y1*py,area.area_extent[0]+x1*px,area.area_extent[3]-y0*py]
    m={'nominal_utc':item['nominal_utc'],'scan_start_utc':start,'scan_end_utc':end,'frame_directory':str(dest.resolve()),
       'material':'neutral measured daytime VIS and night IR display; no synthetic observations',
       'source_manifest':item['manifest'],'support':records,'native_full_grid':[5500,5500],'native_crop_yx':list(SLICE),
       'extent_m':list(map(float,extent)),'projection':area.crs.to_dict(),'cloud_texture_dimensions':list(rgba.shape[1::-1]),
       'vis':vis_record,'height_supported_pixels':int(np.isfinite(height).sum()),'cloudy_pixels':int(cloudy.sum()),
       'height_policy':'Cloud mask2/3 and maskQF0, heightQF0, 0<HT<=20km, delivered ZcError<=3km; missing stays NaN',
       'volume_policy':'Retrieved top compressed for display; any cloud base/thickness/density is an independently labelled approximation, not retrieved optical thickness',
       'night_source_resolution_m':2000,'native_projection_preserved':True,'is_global_cloud_coverage':False}
    m['projection']['a']=float(area.crs.ellipsoid.semi_major_metre)
    m['projection']['b']=float(area.crs.ellipsoid.semi_minor_metre)
    output.write_text(json.dumps(m,indent=2),encoding='utf-8')
    print('FRAME',stamp.isoformat(),'height',m['height_supported_pixels'],'archivedMB',round(sum(r['used_archived_bytes'] for r in records)/1e6,1),flush=True)
    del scene,rgba,t,lon,lat;gc.collect();return m
