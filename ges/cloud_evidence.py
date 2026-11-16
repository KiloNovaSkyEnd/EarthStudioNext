"""Conservative cloud display supported by NOAA L2 mask/phase/pressure.

L2 retrievals are additional algorithm evidence, NOT independent ground truth.
Legacy 2020 AHI files provide embedded lat/lon and image time, but cannot be
read by Satpy's modern AHI-L2 filename/metadata reader without guessing.
We verify their coordinates against the real L1 grid before assigning it.
"""
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import warnings

import netCDF4
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from .catalog import utc_time
from .download import read_manifest
from .solar import solar_weights

TYPE_ATBD='https://www.star.nesdis.noaa.gov/goesr/documents/ATBDs/Enterprise/ATBD_Enterprise_Cloud_Type_v3_2020-06-01.pdf'
HEIGHT_ATBD='https://www.star.nesdis.noaa.gov/goesr/documents/ATBDs/Enterprise/ATBD_Enterprise_Cloud_Height_v3.4_2020-09.pdf'
LABELS={0:'no L2 mask evidence',1:'L2 clear category (ABI binary mask may include probably clear)',2:'quality-screened low liquid/supercooled cloud',
        3:'other L2 confident cloud (not classified as low liquid)',4:'uncertain mask or conflicting evidence',
        5:'quality-screened high ice cloud; NOT convection identification',
        6:'probable-cloud mask with quality-screened low liquid/supercooled retrieval; less certain than class 2',
        7:'nominal low liquid cloud; pressure uncertainty overlaps middle level',
        8:'ABI nominal low liquid cloud; coarse pressure grid, pressure uncertainty not supplied',
        9:'SEVIRI good-quality cloud top below 3 km; phase and height uncertainty not delivered'}
LOW_CLASSES=(2,6,7,8,9)


def evidence_classes(mask,phase,pressure,pressure_error,mask_q,phase_q,height_q,nominal_low=False):
    arrays=[np.asarray(v) for v in (mask,phase,pressure,pressure_error,mask_q,phase_q,height_q)]
    if any(v.shape!=arrays[0].shape for v in arrays):raise ValueError('All L2 fields must be on the identical grid')
    mask,phase,pressure,error,mq,pq,hq=arrays
    valid_mask=np.isin(mask,[0,1,2,3]) & (mq==0)
    classes=np.zeros(mask.shape,dtype=np.uint8)
    classes[valid_mask]=4
    classes[valid_mask & (mask==0) & (phase==0)]=1
    cloudy=valid_mask & (mask==3)
    classes[cloudy]=3
    good=(valid_mask & np.isin(mask,[2,3]) & (pq==0) & (hq==0) & np.isfinite(pressure) & (pressure>0) & (pressure<=1100)
          & np.isfinite(error) & (error>=0) & (error<=1000))
    # Pressure error is the delivered retrieval uncertainty, not an invented
    # confidence probability. Requiring the whole +/- error interval is a
    # conservative display guard, not a guarantee of correct categorization.
    classes[good & np.isin(phase,[1,2]) & (pressure-error>680)]=2
    classes[good & (mask==2) & np.isin(phase,[1,2]) & (pressure-error>680)]=6
    classes[good & cloudy & (phase==4) & (pressure+error<440)]=5
    if nominal_low:
        nominal=good & np.isin(phase,[1,2]) & (pressure>680) & ~np.isin(classes,[2,6])
        classes[nominal]=7
    return classes


def low_tint_weight(classes,feather=1):
    """Fade tint INSIDE supported low-cloud regions; never expand class labels."""
    c=np.asarray(classes)
    if c.ndim!=2 or feather<1:raise ValueError('2D classes and positive feather required')
    supported=np.isin(c,LOW_CLASSES)
    padded=np.pad(np.pad(supported,((0,0),(feather+1,feather+1)),mode='wrap'),((1,1),(0,0)))
    distance=distance_transform_edt(padded)[1:-1,feather+1:-feather-1]
    t=np.clip(distance/(feather+1),0,1)
    t=t*t*(3-2*t)
    return np.where(supported,t,0).astype(np.float32)


def supported_low_visibility(kelvin,spectral_signal):
    """Artistic visibility of an already-supported low cloud, not a retrieval.

    A weak LW-SW difference must not veto the existing L2-supported label.
    Preserve strong spectral texture, add a continuous measured-LW response
    for weak signals. No constant opacity floor or spatial image smoothing.
    This function does not decide whether a pixel is a cloud.
    """
    k=np.asarray(kelvin,dtype=np.float32);signal=np.asarray(spectral_signal,dtype=np.float32)
    if k.shape!=signal.shape or not np.isfinite(signal).all() or not ((signal>=0)&(signal<=1)).all():
        raise ValueError('Matching finite spectral signal in 0..1 required')
    thermal=.65*np.clip((305-np.where(np.isfinite(k),k,305))/55,0,1)**1.3
    thermal=np.where(np.isfinite(k)&(k>=230)&(k<=350),thermal,0)
    return np.maximum(signal,thermal)


def low_cloud_texture(kelvin,shortwave):
    """Continuous measured-band display response; no classification or detail synthesis.

    The old clipped BTD made differences <=1 K and >=4.5 K identical.
    A signed logistic response retains contrast on both sides inside existing
    supported labels. LW shades RGB; missing SW uses only measured LW.
    """
    k=np.asarray(kelvin,dtype=np.float32);sw=np.asarray(shortwave,dtype=np.float32)
    if k.shape!=sw.shape:raise ValueError('Matching LW/SW dimensions required')
    valid=np.isfinite(k)&(k>=230)&(k<=350)
    paired=valid&np.isfinite(sw)&(sw>=100)&(sw<=350)
    difference=np.where(paired,k-np.where(paired,sw,k),0)
    spectral=1/(1+np.exp(-np.clip((difference-2)/1.5,-40,40)))
    thermal=supported_low_visibility(k,np.zeros_like(k))
    visibility=np.where(valid,np.where(paired,.85*spectral+.15*thermal,thermal),0)
    shade=.65+.35*np.clip((305-np.where(valid,k,305))/55,0,1)
    color=shade[...,None]*np.array([.55,.75,.98],dtype=np.float32)
    return visibility,color


def evidence_rgba(kelvin,classes,night,tint_weight=None,latitude=0,low_signal=None,low_shortwave=None):
    k=np.asarray(kelvin,dtype=np.float32);c=np.asarray(classes);n=np.asarray(night,dtype=bool)
    if not k.shape==c.shape==n.shape:raise ValueError('IR/class/night dimensions differ')
    valid=np.isfinite(k)&(k>=100)&(k<=350)&n
    safe=np.where(valid,k,280)
    # Match the original spectral display's continuous cold-IR transfer.
    # A 293 K baseline added a gray veil over warm ocean in v2.
    cold=200+20*np.clip((np.abs(np.asarray(latitude))-30)/30,0,1)
    high=np.where(valid,np.clip((280-safe)/(280-cold),0,1),0)
    if tint_weight is None:tint_weight=np.ones_like(k)
    tint_weight=np.asarray(tint_weight,dtype=np.float32)
    if tint_weight.shape!=k.shape or not np.isfinite(tint_weight).all() or not ((tint_weight>=0)&(tint_weight<=1)).all():
        raise ValueError('Matching finite tint weight in 0..1 required')
    blend=np.where(valid&np.isin(c,LOW_CLASSES),tint_weight,0)
    if low_signal is None:low_signal=np.clip((300-safe)/55,0,1)
    low_signal=np.asarray(low_signal,dtype=np.float32)
    if low_signal.shape!=k.shape or not np.isfinite(low_signal).all() or not ((low_signal>=0)&(low_signal<=1)).all():
        raise ValueError('Matching finite low signal in 0..1 required')
    visibility=supported_low_visibility(k,low_signal)
    color=np.array([.55,.75,.98])
    if low_shortwave is not None:
        visibility,color=low_cloud_texture(k,low_shortwave)
    low=blend*visibility
    alpha=high+(1-high)*low
    premult=high[...,None]+((1-high)*low)[...,None]*color
    rgb=np.divide(premult,alpha[...,None],out=np.zeros_like(premult),where=alpha[...,None]>0)*255
    rgba=np.empty(k.shape+(4,),dtype=np.uint8)
    rgba[...,:3]=np.rint(rgb).astype(np.uint8)
    rgba[...,3]=np.rint(alpha*255).astype(np.uint8)
    return rgba


def _values(file,name):
    variable=file[name]
    if name=='CloudPhaseFlag' and variable.ndim==3 and variable.shape[-1]==1:
        # Legacy file contains one explicit quality flag per pixel in a
        # singleton trailing dimension. Do not collapse multi-flag products.
        data=variable[:,:,0]
    else:
        data=variable[:]
    return np.ma.filled(data.astype(np.float32),np.nan)


def legacy_ahi_evidence(files,area,ir_start,ir_end):
    """Read native categorical fields, verify time/units and actual navigation."""
    paths={kind:next(Path(p) for p in files if f'CLOUD_{kind}_EN.nc' in Path(p).name)
           for kind in ['MASK','PHASE','HEIGHT']}
    values={};dates=[];navigation=[]
    # Distributed test points within the disk, including both hemispheres.
    xx=np.array([1500,2500,3500,4500,1200,4000,1800,3200])
    yy=np.array([1500,2500,3500,2500,3000,1800,3800,4000])
    expected_lon,expected_lat=area.get_lonlat_from_array_coordinates(xx,yy)
    for kind,path in paths.items():
        with netCDF4.Dataset(path) as data:
            if data['Latitude'].shape!=area.shape:raise ValueError('Legacy AHI L2 and actual IR grids differ')
            image_time=datetime.strptime(str(data.Image_Date)+str(data.Image_Time),'%Y%j%H%M_%S').replace(tzinfo=timezone.utc)
            # Legacy Image_Time has whole-second precision; the L1 first pixel
            # can start at e.g. 16:40:21.953 within the 16:40:21 L2 time bin.
            if image_time+timedelta(seconds=1)<utc_time(ir_start) or image_time>utc_time(ir_end):
                raise ValueError('AHI L2 one-second image-time bin does not overlap actual IR scan')
            dates.append(image_time.isoformat().replace('+00:00','Z'))
            lon=np.array([data['Longitude'][y,x] for x,y in zip(xx,yy)])
            lat=np.array([data['Latitude'][y,x] for x,y in zip(xx,yy)])
            delta_lon=float(np.max(np.abs((lon-expected_lon+180)%360-180)))
            delta_lat=float(np.max(np.abs(lat-expected_lat)))
            if not np.isfinite([delta_lon,delta_lat]).all() or max(delta_lon,delta_lat)>.001:
                raise ValueError('L2 embedded geolocation does not match real L1 navigation')
            navigation.append({'file':path.name,'max_sample_longitude_error_deg':delta_lon,'max_sample_latitude_error_deg':delta_lat})
            if int(data['granule_level_quality_flag'][:])!=0:raise ValueError('Degraded legacy AHI L2 granule; refuse verified-blue display')
            for key in {'MASK':['CloudMask','CloudMaskQualFlag'],
                        'PHASE':['CloudPhase','CloudPhaseFlag'],
                        'HEIGHT':['CldTopPres','PcError','CloudHgtQF']}[kind]:
                if key in ['CldTopPres','PcError'] and data[key].units!='hPa':raise ValueError('Pressure and error must be delivered in hPa')
                values[key]=_values(data,key)
    if len(set(dates))!=1:raise ValueError('AHI mask/phase/pressure image times differ')
    classes=evidence_classes(values['CloudMask'],values['CloudPhase'],values['CldTopPres'],values['PcError'],
                             values['CloudMaskQualFlag'],values['CloudPhaseFlag'],values['CloudHgtQF'],nominal_low=True)
    low=np.isin(classes,[2,6])
    stats={'native_grid_class_counts':{str(k):int((classes==k).sum()) for k in LABELS},
           'low_liquid_pressure_minus_error_min_hpa':float(np.min((values['CldTopPres']-values['PcError'])[low])) if low.any() else None,
           'product_image_utc':dates[0],'scan_interval_in_L2_file':'not provided; actual L1 scan bounds retained separately',
           'navigation_checks':navigation,'references':[TYPE_ATBD,HEIGHT_ATBD],
           'quality_policy':'mask=2/3, all quality=0, liquid phase; strict pressure-error>680 classes 2/6, nominal pressure>680 class 7 with uncertain layer interval; granule flags=0'}
    return classes,stats


def render_cloud_evidence(ir_manifest,l2_manifest,lights,out_dir,width=8192):
    ir_manifest,l2_manifest,lights,out_dir=map(Path,[ir_manifest,l2_manifest,lights,out_dir])
    meta=read_manifest(ir_manifest);l2=read_manifest(l2_manifest)
    satellite=meta['satellite']
    ahi=satellite=='himawari8' and l2['product']=='AHI-L2-FLDK-Clouds'
    abi=satellite.startswith('goes') and l2['product']=='ABI-L2-ACM-ACTP-ACHA-CTP'
    seviri=satellite.startswith('meteosat_') and l2['product']=='SEVIRI-L2-CLM-CTH'
    if not (ahi or abi or seviri) or l2['satellite']!=satellite+'_cloud_l2':
        raise ValueError('Matching supported AHI legacy or ABI L2 manifest family required')
    if any(path.parent.resolve()==out_dir.resolve() or path.parent.resolve() in out_dir.resolve().parents for path in [ir_manifest,l2_manifest,lights]):
        raise ValueError('Processed output must not be inside raw input directories')
    # L2 constrains category; the verified shortwave/longwave pair supplies
    # the original continuous spectral texture rather than fixed blue alpha.
    from .multispectral import calibrated_pair,night_layers
    scene,bands,start,end,policies=calibrated_pair(meta)
    ir_attrs=scene[bands[0]].attrs
    expected_um=10.8 if seviri else 10.4
    if ir_attrs.get('units')!='K' or abs(ir_attrs['wavelength'].central-expected_um)>.15:
        raise ValueError('Actual calibrated 10.4 um Kelvin longwave IR required')
    if ahi:classes,stats=legacy_ahi_evidence(l2['local_files'],ir_attrs['area'],start,end)
    elif abi:
        from .abi_cloud_evidence import load_abi_evidence
        classes,stats=load_abi_evidence(l2['local_files'],ir_attrs['area'],start,end,satellite)
    else:
        from .seviri_cloud_evidence import load_seviri_evidence
        classes,stats=load_seviri_evidence(l2['local_files'],ir_attrs['area'],ir_attrs,start,end)
    # Direct inverse navigation assigns the actual containing native pixel,
    # avoiding KD-tree radius holes and beyond-limb geographic borrowing.
    from .geosampling import inverse_global,limb_visibility
    import dask
    native_lw,native_sw=dask.compute(scene[bands[0]].data,scene[bands[1]].data)
    lw,sw,c=inverse_global(ir_attrs['area'],[np.ma.filled(native_lw,np.nan),np.ma.filled(native_sw,np.nan),classes],width)
    del native_lw,native_sw,classes
    sw=np.ma.filled(sw,np.nan)
    lw=np.ma.filled(lw,np.nan);c=np.where(np.isfinite(c),c,0).astype(np.uint8)
    c=np.where(np.isin(c,list(LABELS)),c,0).astype(np.uint8)
    tint=low_tint_weight(c)
    coverage=np.isfinite(lw)&(lw>=100)&(lw<=350)
    rgba=np.zeros(lw.shape+(4,),dtype=np.uint8);night=np.zeros(lw.shape,dtype=np.uint8)
    lon=-180+(np.arange(width)+.5)*360/width
    ref=json.loads(lights.with_suffix('.json').read_text(encoding='utf-8'))
    if ref.get('kind')!='static reference night-lights composite, not contemporaneous with satellite clouds':
        raise ValueError('Documented static night lights required')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',Image.DecompressionBombWarning)
        with Image.open(lights) as image:
            if image.size!=(ref['width'],ref['height']):raise ValueError('Static-light dimensions differ from provenance')
            surface=np.asarray(image.convert('RGB').resize((width,width//2),Image.Resampling.LANCZOS)).copy()
    for row in range(0,width//2,128):
        sl=slice(row,min(row+128,width//2));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
        first=solar_weights(utc_time(start),lon[None,:],lat[:,None])
        last=solar_weights(utc_time(end),lon[None,:],lat[:,None])
        eligible=coverage[sl]&(first.elevation_deg<=-6)&(last.elevation_deg<=-6)
        night[sl]=eligible.astype(np.uint8)*255
        _,_,_,low,_=night_layers(lw[sl],sw[sl],lat[:,None],first.elevation_deg,last.elevation_deg)
        rgba[sl]=evidence_rgba(lw[sl],c[sl],eligible,tint[sl],lat[:,None],low,low_shortwave=sw[sl])
        fade=limb_visibility(ir_attrs['area'],lon[None,:],lat[:,None])
        rgba[sl,...,3]=np.rint(rgba[sl,...,3].astype(np.float32)*fade).astype(np.uint8)
        surface[sl]=np.maximum(np.rint(surface[sl]*first.city_lights[...,None]).astype(np.uint8),(4,5,12))
    c[~coverage]=0
    surface[~coverage]=(24,11,35)
    # Uncertainty remains in the separate class map, never as a hard surface
    # recoloring in the cinematic display. Neutral IR is not a cloud label.
    out_dir.mkdir(parents=True,exist_ok=True)
    stem='ahi_evidence_night' if ahi else satellite+'_evidence_night'
    target=out_dir/(stem+'.png');surface_path=out_dir/(stem+'_surface.png')
    Image.fromarray(rgba).save(target);Image.fromarray(surface).save(surface_path)
    Image.fromarray(coverage.astype(np.uint8)*255).save(out_dir/(stem+'_coverage.png'))
    Image.fromarray(c).save(out_dir/(stem+'_classes.png'))
    Image.fromarray(night).save(out_dir/(stem+'_eligible.png'))
    alpha=rgba[...,3:4].astype(np.float32)/255
    Image.fromarray(np.rint(rgba[...,:3]*alpha+surface*(1-alpha)).astype(np.uint8)).save(out_dir/(stem+'_preview.png'))
    blue=(rgba[...,2]>rgba[...,0])&(rgba[...,3]>0)
    assert not (blue & ~np.isin(c,LOW_CLASSES)).any()
    assert not (rgba[~coverage,3]>0).any() and not (rgba[night==0,3]>0).any()
    metadata={'product':'ir-night-display','display_recipe':'cloud-evidence-signed-texture-v8','satellite':satellite,
              'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':width,'height':width//2,
              'reference_utc':meta['observed_utc'],'observed_utc':meta['observed_utc'],
              'navigation_recipe':'inverse-native-geos-pixel-footprint-v1',
              'pixel_method':'inverse source projection; containing native pixel; invalid native sample stays missing; no geographic nearest-valid borrowing',
              'limb_display_policy':'alpha only smoothstep(view cosine/0.08) using actual geos ellipsoid/height; native coverage retained separately; central RGB/transfer unchanged from accepted v8',
              'scan_start_utc':start,'scan_end_utc':end,'source_ir_manifest':str(ir_manifest.resolve()),
              'source_l2_manifest':str(l2_manifest.resolve()),'source_ir_coverage':stem+'_coverage.png',
              'cloud_evidence_classes':stem+'_classes.png','class_labels':LABELS,
              'l2_verification':stats,'displayed_blue_pixels':int(blue.sum()),
              'observed_pixels':int(coverage.sum()),'is_opacity_retrieval':False,
              'tint_feather_grid_pixels':1,'continuous_neutral_ir_is_cloud_classification':False,
              'blue_texture':'Continuous signed LW-SW logistic display and measured LW RGB shading gated by L2 low-top classes 2/6/7/8/9; separate phase/height/pressure uncertainty retained',
              'supported_low_visibility':'0.85*s+0.15*t when paired, otherwise t; s=logistic((LW-SW-2)/1.5), t=0.65*clip((305-LW_K)/55,0,1)^1.3; only LW>=230 K; display opacity, NOT optical depth or cloud classification',
              'low_rgb_shading':'[0.55,0.75,0.98]*(0.65+0.35*clip((305-LW_K)/55,0,1)); measured LW shade; no synthesized texture or spatial sharpening',
              'shortwave_missing_policy':'Existing L2-supported low clouds may use measured LW visibility when SW is weak/missing; no missing SW observation inferred',
              'band_time_quality_policy':policies,
              'is_convection_classification':False,'is_independent_ground_truth_validation':False,
              'low_cloud_support_basis':'good-quality cloud top below 3 km; no phase retrieval' if seviri else 'quality-screened cloud mask, liquid phase and cloud top pressure; uncertainty retained',
              'same_physical_class_definition_across_sensors':False,
              'limitations':'Satellite L2 algorithms are additional same-sensor retrieval evidence, not independent truth. '
                            'Only cloud tops are classified; low clouds under high cloud cannot be inferred. '
                            'Conservative quality and pressure-uncertainty guards may miss real low clouds. '
                            'Continuous cold-IR alpha and spectral blue alpha are display choices, not optical depth. '
                            'Neutral IR is preserved for uncertain/clear categories and can contain cold ground; it is not a cloud mask. '
                            'Cloud mask/phase/pressure may still be wrong. Night-only research display; '
                            'nominal low classes 7/8 are not strict pressure-interval classifications; '
                            'SEVIRI class 9 is height-based and has no liquid-phase retrieval.'}
    target.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    surface_path.with_suffix('.json').write_text(json.dumps({
        'kind':'static night reference with computed solar gating and missing-IR tint','source_reference':ref,
        'source_image':str(lights.resolve()),'model_utc':meta['observed_utc'],'projection':'EPSG:4326',
        'extent_wsen':[-180,-90,180,90],'width':width,'height':width//2,
        'is_contemporaneous_observation':False,'uncertainty_display':'separate class map; no hard tint in film surface'},indent=2),encoding='utf-8')
    return target


render_ahi_evidence=render_cloud_evidence  # Existing Python callers remain compatible.
