"""Observed daylight RGB + measured twilight IR + accepted deep-night display."""
from pathlib import Path
import json
import numpy as np
from PIL import Image
from .catalog import utc_time
from .solar import solar_weights,_smoothstep
from .geosampling import inverse_global,limb_visibility
from .download import read_manifest
from .render import create_satpy_scene,mask_goes_ir_quality,observation_interval
from .cloud_evidence import evidence_rgba,low_tint_weight
from .blend_night import mix_pixels,linear_rgb,encode_rgb


def verify_lw_interval(actual,accepted,satellite):
    if None in actual:raise ValueError('Missing actual LW interval')
    start,end=map(utc_time,actual);first,last=map(utc_time,accepted)
    if end<start:raise ValueError('Reversed actual LW scan')
    if satellite.startswith('himawari'):
        # Accepted pair records the union of B07/B13 detector windows. Existing
        # verified AHI offset is <1 second; an individual LW scan lies inside.
        if not (0<=(start-first).total_seconds()<=1 and 0<=(last-end).total_seconds()<=1):
            raise ValueError('AHI LW is not within the verified one-second pair union')
    elif (start,end)!=(first,last):raise ValueError('Actual LW scan differs from accepted source')


def transition_ir(old,lw,elevation_start,elevation_end,latitude,limb=1,classes=None,tint=None):
    valid=np.isfinite(lw)&(lw>=100)&(lw<=350)
    neutral=evidence_rgba(lw,np.full(lw.shape,3) if classes is None else classes,valid,
                          tint_weight=tint,latitude=latitude,low_signal=np.zeros(lw.shape))
    # Original L2 low-top support may expose warm clouds through LW thermal
    # visibility. White only: sunlight-contaminated SW is not used.
    neutral[...,:3]=np.where(neutral[...,3:4]>0,255,0)
    neutral[...,3]=np.rint(neutral[...,3].astype(np.float32)*limb).astype(np.uint8)
    # Blue SW signal is retained only well inside actual night. No SW inference
    # is used in twilight; measured LW supplies neutral IR there.
    deep=np.broadcast_to(_smoothstep(-np.maximum(elevation_start,elevation_end),6,12),lw.shape)
    result=mix_pixels([old,neutral],[deep.astype(np.float32),(1-deep).astype(np.float32)])
    result[deep>=1]=old[deep>=1];result[deep<=0]=neutral[deep<=0];result[~valid]=0
    return result


def render_transition(record,out_dir,width=8192,supported_twilight=False):
    oldpath=Path(record['image']);m=json.loads(oldpath.with_suffix('.json').read_text())
    if m.get('navigation_recipe')!='inverse-native-geos-pixel-footprint-v1' or m['width']!=width:
        raise ValueError('Matching validated native-navigation night source required')
    raw=read_manifest(Path(m['source_ir_manifest']));sat=raw['satellite']
    band='B13' if sat.startswith('himawari') else 'C13' if sat.startswith('goes') else 'IR_108'
    scene=create_satpy_scene(raw['local_files'],sat);scene.load([band]);a=scene[band].attrs
    if a.get('units')!='K':raise ValueError('Actual Kelvin LW required')
    verify_lw_interval(observation_interval(a),(m['scan_start_utc'],m['scan_end_utc']),sat)
    if sat.startswith('goes'):mask_goes_ir_quality(scene,raw['local_files'],band)
    lw=inverse_global(a['area'],[np.ma.filled(scene[band].compute().values,np.nan)],width)[0]
    old=np.asarray(Image.open(oldpath));coverage=np.asarray(Image.open(oldpath.parent/m['source_ir_coverage']))>0
    actual=np.isfinite(lw)&(lw>=100)&(lw<=350)
    if not np.array_equal(actual,coverage):raise ValueError('Transition IR changed verified native coverage')
    classes=np.asarray(Image.open(oldpath.parent/m['cloud_evidence_classes'])) if supported_twilight else None
    tint=low_tint_weight(classes) if supported_twilight else None
    result=np.zeros_like(old);lon=-180+(np.arange(width)+.5)*360/width
    for row in range(0,width//2,128):
        sl=slice(row,min(row+128,width//2));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
        first=solar_weights(utc_time(m['scan_start_utc']),lon[None,:],lat[:,None]).elevation_deg
        last=solar_weights(utc_time(m['scan_end_utc']),lon[None,:],lat[:,None]).elevation_deg
        result[sl]=transition_ir(old[sl],lw[sl],first,last,lat[:,None],limb_visibility(a['area'],lon[None,:],lat[:,None]),
                                classes[sl] if supported_twilight else None,tint[sl] if supported_twilight else None)
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True);target=out_dir/(sat+'_transition_ir.png')
    Image.fromarray(result).save(target);cov=target.with_name(target.stem+'_coverage.png')
    Image.fromarray(coverage.astype(np.uint8)*255).save(cov)
    meta={**m,'display_recipe':'night-transition-supported-v1','source_ir_coverage':cov.name,
          'deep_night_base_image':str(oldpath.resolve()),'deep_night_base_recipe':m['display_recipe'],
          'cloud_evidence_classes':str((oldpath.parent/m['cloud_evidence_classes']).resolve()),
          'deep_night_base_displayed_blue_pixels':m.get('displayed_blue_pixels'),
          'displayed_blue_pixels':int(((result[...,2]>result[...,0])&(result[...,3]>0)).sum()),
          'transition_actual_lw_interval':list(observation_interval(a)),
          'transition_policy':'accepted source RGBA exactly retained if BOTH solar elevations <=-12; blend to measured neutral LW IR between -12 and -6; no blue SW interpretation in twilight/day; day selection must be applied externally',
          'not_standalone_film':True}
    if supported_twilight:
        meta.update(display_recipe='night-transition-supported-v2',
            warm_twilight_clouds='Original quality-screened L2 low-top support with existing LW thermal visibility; neutral white only; no SW sunlight interpretation or new cloud class',
            transition_policy=meta['transition_policy']+'; neutral warm clouds retained only with original L2 class support')
    target.with_suffix('.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    return {**record,'image':str(target.resolve())}


def compose_pixels(day,night_cloud,night_surface,day_weight,night_coverage,ir_fallback=False):
    day=np.asarray(day);cloud=np.asarray(night_cloud);surface=np.asarray(night_surface)
    w=np.asarray(day_weight,dtype=np.float32);coverage=np.asarray(night_coverage,dtype=bool)
    if day.shape!=cloud.shape or day.shape[-1]!=4 or surface.shape!=day.shape[:-1]+(3,) or w.shape!=day.shape[:-1] or coverage.shape!=w.shape:
        raise ValueError('Matching RGBA, surface and weight/coverage grids required')
    if not np.isfinite(w).all() or ((w<0)|(w>1)).any():raise ValueError('Finite day weights in 0..1 required')
    ca=cloud[...,3:4].astype(np.float32)/255
    night=np.rint(cloud[...,:3]*ca+surface*(1-ca)).astype(np.uint8)
    dw=w*(day[...,3].astype(np.float32)/255)
    nw=(1-dw if ir_fallback else 1-w)*coverage
    alpha=dw+nw
    premult=linear_rgb(day[...,:3])*dw[...,None]+linear_rgb(night)*nw[...,None]
    rgb=encode_rgb(np.divide(premult,alpha[...,None],out=np.zeros_like(premult),where=alpha[...,None]>0))
    return np.dstack([rgb,np.rint(alpha*255).astype(np.uint8)]),dw,nw


def compose_day_night(day_path,night_path,out,reference_utc):
    day_path,night_path,out=map(Path,[day_path,night_path,out]);stamp=utc_time(reference_utc)
    dm=json.loads(day_path.with_suffix('.json').read_text());nm=json.loads(night_path.with_suffix('.json').read_text())
    if dm.get('product')!='daylight-rgb' or nm.get('product')!='ir-night-display':raise ValueError('Verified day and transition IR products required')
    if not nm.get('sources') or any(s.get('provenance',{}).get('display_recipe') not in ['night-transition-supported-v1','night-transition-supported-v2'] for s in nm['sources']):
        raise ValueError('Measured transition IR branch is required; legacy night-only PNG cannot supply twilight')
    for m in [dm,nm]:
        if m['projection']!='EPSG:4326' or m['extent_wsen']!=[-180,-90,180,90]:raise ValueError('Global source grid required')
        if abs((utc_time(m.get('reference_utc',m['observed_utc']))-stamp).total_seconds())>1200:raise ValueError('Source >20 minutes from reference')
    if (dm['width'],dm['height'])!=(nm['width'],nm['height']):raise ValueError('Day/night grid sizes differ')
    if out.suffix.lower()!='.png' or out.resolve() in [day_path.resolve(),night_path.resolve()]:raise ValueError('New PNG output required; cannot overwrite inputs')
    for p,m in [(day_path,dm),(night_path,nm)]:
        with Image.open(p) as im:
            if im.mode!='RGBA' or im.size!=(m['width'],m['height']):raise ValueError('Actual RGBA grid differs from provenance')
    day=np.asarray(Image.open(day_path));cloud=np.asarray(Image.open(night_path))
    surface=np.asarray(Image.open(night_path.parent/nm['night_surface'])).copy()
    rawcov=np.asarray(Image.open(night_path.parent/nm['source_ir_coverage']))
    if not np.isin(rawcov,[0,255]).all():raise ValueError('Binary measured IR coverage required')
    coverage=rawcov>0
    modern=dm.get('display_recipe')=='abi-rayleigh-cold-cloud-log-v2'
    if modern:
        from scipy.ndimage import distance_transform_edt
        from .day_atmosphere import geocolor_day_weight
        view=np.asarray(Image.open(day_path.parent/dm['source_view_weight']),dtype=np.float32)/255
        # Feather only within actually valid VIS. No neighbor pixel is copied.
        edge=_smoothstep(distance_transform_edt(day[...,3]>0),0,4)
        # CIRA blends complete day/night stacks ONCE. V1 had already gated the
        # entire night reference at -6..0 degrees, causing a second black fade.
        from .storage import load_config
        import hashlib,warnings
        refpath=load_config().raw_dir/'reference/BlackMarble_2016_3km.jpg'
        ref=json.loads(refpath.with_suffix('.json').read_text(encoding='utf-8'))
        if ref.get('kind')!='static reference night-lights composite, not contemporaneous with satellite clouds':
            raise ValueError('Verified static nighttime background required')
        with refpath.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=ref['sha256']:raise ValueError('Static reference hash differs')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',Image.DecompressionBombWarning)
            with Image.open(refpath) as im:
                if im.size!=(ref['width'],ref['height']):raise ValueError('Reference dimensions differ')
                static_surface=np.maximum(np.asarray(im.convert('RGB').resize((dm['width'],dm['height']),Image.Resampling.LANCZOS)),(4,5,12)).astype(np.uint8)
    h,w=coverage.shape;rgba=np.zeros_like(day);daymap=np.zeros((h,w),dtype=np.uint8);nightmap=np.zeros_like(daymap)
    missing=np.zeros_like(daymap);fallback=np.zeros_like(daymap);lon=-180+(np.arange(w)+.5)*360/w
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        solar=solar_weights(stamp,lon[None,:],lat[:,None])
        if modern:surface[sl]=np.where((solar.elevation_deg>-6)[...,None],static_surface[sl],surface[sl])
        weight=geocolor_day_weight(solar.elevation_deg)*view[sl]*edge[sl] if modern else solar.day_cloud
        rgba[sl],dw,nw=compose_pixels(day[sl],cloud[sl],surface[sl],weight,coverage[sl],ir_fallback=modern)
        daymap[sl]=np.rint(dw*255).astype(np.uint8);nightmap[sl]=np.rint(nw*255).astype(np.uint8)
        missing[sl]=np.rint((1-dw-nw)*255).astype(np.uint8)
        if modern:fallback[sl]=((geocolor_day_weight(solar.elevation_deg)>0)&(day[sl,...,3]==0)&coverage[sl]).astype(np.uint8)*255
    out.parent.mkdir(parents=True,exist_ok=True);Image.fromarray(rgba).save(out)
    for label,values in [('day_contribution',daymap),('night_contribution',nightmap),('missing_requested_weight',missing)]:
        Image.fromarray(values).save(out.with_name(out.stem+'_'+label+'.png'))
    if modern:Image.fromarray(fallback).save(out.with_name(out.stem+'_measured_ir_day_gap.png'))
    metadata={'product':'day-night-display','display_recipe':'observed-abi-day-supported-ir-night-v1',
        'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':w,'height':h,
        'observed_utc':reference_utc,'reference_utc':reference_utc,'day_source':dm,'night_source':nm,
        'contains_surface_and_clouds':True,'alpha_meaning':'available requested source weight; NOT cloud opacity',
        'day_night_transition':'solar day weight smoothstep(0..+6 deg); IR complementary; source availability retained in alpha, never renormalized to opaque missing VIS',
        'deep_night_color':'accepted v8 display retained away from -12..-6 degree twilight transition',
        'night_lights':'independent static NASA 2016 reference in night source, not 2020 contemporaneous',
        'daylight_scope':'GOES-16 only; no claimed AHI/SEVIRI daylight coverage',
        'limitations':'Day RGB contains actual surface/cloud imagery; no day cloud opacity or height retrieval. Night IR+reference is a display approximation. Flattened geographic view, no 3D cloud heights/volumes. Missing VIS and polar gaps remain. Different acquisition scan times retained.'}
    if modern:
        metadata.update(display_recipe='observed-rayleigh-day-measured-ir-fallback-v2',
            day_night_transition='Miller2020 Nmu=clip((sin(elevation)-.1)/.2,0,1)^1.5; day-side fade +5.74..+17.46deg; view fade65..80deg; inward four-pixel VIS support feather',
            missing_visible_policy='Unusable VIS stays masked. Complementary weight uses measured neutral LW IR, including day gaps; never claimed as visible RGB. Both missing remains transparent.',
            alpha_meaning='union of weighted actual VIS and measured IR coverage; NOT cloud opacity',
            source_contributions='day_contribution is real visible weight; night_contribution includes explicitly measured daytime IR fallback',
            measured_ir_day_gap_pixels=int((fallback>0).sum()),
            static_reference=ref,
            twilight_background='Complete NASA2016 night stack blended once with CIRA solar factor; static cities may appear in day-side transition as display reference, not contemporary observed lights. Original deep night retained.',
            reference='https://repository.library.noaa.gov/view/noaa/30693/noaa_30693_DS1.pdf')
    out.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8');return out
