"""Isolated A/B GeoColor study; installed Satpy official recipes, no renderer integration."""
import argparse
from datetime import timedelta
import hashlib
import inspect
import json
import os
from pathlib import Path

import dask
import numpy as np
from PIL import Image
import satpy
from satpy import Scene
from satpy.enhancements.enhancer import get_enhanced_image
from ges.storage import load_config
from ges.catalog import utc_time
from ges.render import observation_interval
from ges.solar import solar_weights
from ges.goni_lowcloud import daylight_material,night_material,low_liquid_confidence,spectral_night_material,evidence_tinted_night_material,screen_confident_clear
from scripts.soften_goni_boundaries import inward_feather

# Native AHI 2km indices. This is a declared fixed projected study rectangle.
R0,R1,C0,C1=900,2050,1500,3000


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def array(data):
    return np.asarray(data.compute(scheduler='threads',num_workers=2).data,np.float32)


def save_unit(path, values):
    a=np.asarray(values)
    Image.fromarray(np.rint(np.clip(np.nan_to_num(a),0,1)*255).astype(np.uint8)).save(path)


def official(stamp,dest):
    cfg=load_config();root=cfg.raw_dir/'hinnamnor_geocolor_v1'/stamp.strftime('%Y%m%dT%H%M%SZ')
    files=sorted(str(p.resolve()) for p in root.glob('*.DAT.bz2'))
    assert len(files)==18
    reference=cfg.raw_dir/'reference/satpy_geocolor_v060'
    os.environ['PSP_CONFIG_FILE']=str((cfg.raw_dir/'reference/pyspectral/pyspectral.yaml').resolve())
    from pyspectral.rayleigh import Rayleigh
    corrector=Rayleigh('Himawari-8','ahi',atmosphere='us-standard',aerosol_type='rayleigh_only')
    assert not corrector.do_download
    dest.mkdir(parents=True,exist_ok=True)
    with satpy.config.set(data_dir=str(reference.resolve()),download_aux=False), dask.config.set(num_workers=2):
        scene=Scene(reader='ahi_hsd',filenames=files)
        scene.load(['B13','B07','B03'])
        base=scene['B13'].attrs['area']; area2=base[R0:R1,C0:C1]
        lon2,lat2=area2.get_lonlats()
        raw={};band_meta={}
        for name in ['B13','B07']:
            data=scene[name];raw[name]=array(data.isel(y=slice(R0,R1),x=slice(C0,C1)))
            band_meta[name]={'units':data.attrs['units'],'wavelength':list(data.attrs['wavelength']),
                             'observation_interval_utc':observation_interval(data.attrs),
                             'start_time':data.attrs['start_time'].isoformat(),'end_time':data.attrs['end_time'].isoformat()}
            assert data.attrs['units']=='K'
        vis=scene['B03'];assert vis.attrs['units']=='%'
        # The current material uses conservative 500m->1km averaging.
        v=vis.isel(y=slice(R0*4,R1*4),x=slice(C0*4,C1*4)).data
        raw['B03_fraction_1km']=np.asarray(v.reshape(((R1-R0)*2,2,(C1-C0)*2,2)).mean(axis=(1,3)).compute(num_workers=2),np.float32)/100
        raw['longitude_2km']=lon2.astype(np.float32);raw['latitude_2km']=lat2.astype(np.float32)
        np.savez_compressed(dest/'observed_inputs.npz',**raw)
        # Load available composites/prerequisites, then use Scene.resample to
        # match this 1km grid and generate deferred composites. IR remains 2km.
        target=area2.copy(width=area2.width*2,height=area2.height*2,area_id='hinnamnor_fixed_1km')
        products=['geo_color','geo_color_high_clouds','geo_color_low_clouds','geo_color_night',
                  'true_color_ndvi_green','_night_background_hires']
        # Generate available prerequisites first, including the official static
        # GeoTIFFs, so Scene.resample also resamples those to the common grid.
        scene.load(products,generate=True,unload=False)
        print('OFFICIAL PREREQUISITES LOADED',stamp.isoformat(),flush=True)
        # Scene.resample automatically reduces each source area. A single xy
        # crop is invalid here because geos bands and lat/lon GeoTIFFs differ.
        result=scene.resample(target,resampler='nearest',radius_of_influence=5000,unload=False)
        print('OFFICIAL GENERATED',list(result.keys()),flush=True)
        fields={}
        for name in products:
            data=result[name]
            rendered=get_enhanced_image(data).data
            pixels=array(rendered.transpose('y','x','bands'))
            save_unit(dest/('A_'+name+'.png'),pixels)
            if name in ['geo_color_high_clouds','geo_color_low_clouds']:
                fields[name+'_raw_alpha']=array(data.sel(bands='A'))
                fields[name+'_enhanced_alpha']=pixels[...,-1]
                if name=='geo_color_high_clouds':fields['high_grey']=pixels[...,0]
            elif name=='_night_background_hires':fields['official_night_background']=pixels[...,:3]
            elif name=='true_color_ndvi_green':fields['official_day_rgb']=pixels[...,:3]
            elif name=='geo_color':fields['official_geo_rgb']=pixels[...,:3]
            elif name=='geo_color_night':fields['official_night_rgb']=pixels[...,:3]
            print('SAVED OFFICIAL',name,flush=True)
        fields['land_water_mask']=array(result['_geo_color_low_clouds_dep_2'].squeeze(drop=True))
        lon,lat=target.get_lonlats();fields['longitude']=lon.astype(np.float32);fields['latitude']=lat.astype(np.float32)
        fields['B13_1km']=np.repeat(np.repeat(raw['B13'],2,0),2,1)
        fields['B07_1km']=np.repeat(np.repeat(raw['B07'],2,0),2,1)
        np.savez_compressed(dest/'official_layers.npz',**fields)
        record={'satpy_version':satpy.__version__,'nominal_utc':stamp.isoformat(),'native_crop_yx':[R0,R1,C0,C1],
                'output_shape_yx':list(target.shape),'area_extent_m':list(map(float,target.area_extent)),
                'projection':target.crs.to_dict(),'resampling':'Scene.load(generate=True), then Scene.resample nearest radius5000m; available prerequisites before resampling, deferred composites afterward',
                'input_file_sha256':{p:sha(p) for p in files},'bands':band_meta,'official_config_unmodified':True,
                'aux_download_disabled':True,'pyspectral_download_disabled':True}
        (dest/'official_metadata.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    return record


def project(stamp,dest,*,source=None,low_cloud_tint_strength=1.,diagnostics=True,region_policy='legacy',low_cloud_display='legacy',colour_control=False,save_layers=True):
    """Pointwise translation of current native v6 material on the same ROI/grid.

    Reuses the actual production transfer functions; does not call fixed-Goni
    preparation scripts which would overwrite Goni outputs. No shader rendering.
    """
    source=dest if source is None else Path(source)
    with np.load(source/'observed_inputs.npz') as data:raw={k:data[k] for k in data.files}
    with np.load(source/'l2_observed_roi.npz') as data:l2={k:data[k] for k in data.files}
    if diagnostics:
        with np.load(source/'official_layers.npz') as data:a={k:data[k] for k in data.files}
    meta=json.loads((source/'official_metadata.json').read_text())
    r0,r1,c0,c1=meta.get('native_crop_yx',[R0,R1,C0,C1])
    assert region_policy in ['legacy','observed','observed_screened'] and low_cloud_display in ['legacy','evidence']
    assert raw['B13'].shape==(r1-r0,c1-c0)
    schemas=json.loads((source/'l2_schema.json').read_text())
    nav_errors=[]
    for schema in schemas:
        for point in schema['navigation']:
            y,x=point['row']-r0,point['column']-c0
            nav_errors.append(max(abs(point['longitude']-raw['longitude_2km'][y,x]),abs(point['latitude']-raw['latitude_2km'][y,x])))
    assert max(nav_errors)<.002
    t,sw=raw['B13'],raw['B07'];valid=np.isfinite(t)&(t>=100)&(t<=350)
    mask,q=l2['CloudMask'],l2['CloudMaskQualFlag'];binary=np.isin(mask,[2,3])&(q==0)
    y,x=np.indices(t.shape);y+=r0;x+=c0
    # Preserve the existing native v6 probability/phase ROI and its inward join.
    edge=np.minimum.reduce([y-1200+1,x-1600+1,2600-y,3400-x])
    join=np.clip(edge/16,0,1).astype(np.float32);join=join*join*(3-2*join)
    inside=(y>=1200)&(y<2600)&(x>=1600)&(x<3400)
    if region_policy.startswith('observed'):
        # All these pixels have independently checked real L2 input. No Goni
        # rectangle switches probability, tone or phase policy within this grid.
        inside=np.ones(t.shape,bool);join=np.ones(t.shape,np.float32)
    native_p=l2['CloudProbability'];good=np.isfinite(native_p)&(native_p>=0)&(native_p<=1)&(q==0)&np.isin(mask,[0,1,2,3])
    p=np.where(inside,np.where(good,binary*(1-join)+native_p*join,0),binary).astype(np.float32)
    if region_policy=='observed_screened':p=screen_confident_clear(p,mask,q)
    low=low_liquid_confidence(mask,q,l2['CloudPhase'],l2['CloudPhaseFlag'],
                              l2['CldTopHght']/1000,l2['ZcError']/1000,l2['CloudHgtQF'])*join
    low*=inside
    lo,la=raw['longitude_2km'],raw['latitude_2km']
    e=solar_weights(stamp,lo,la).elevation_deg
    start,end=meta['bands']['B13']['observation_interval_utc']
    sstart,send=meta['bands']['B07']['observation_interval_utc']
    assert abs((utc_time(start)-utc_time(sstart)).total_seconds())<=1
    assert abs((utc_time(end)-utc_time(send)).total_seconds())<=1
    first=solar_weights(utc_time(start),lo,la).elevation_deg
    final=solar_weights(utc_time(end),lo,la).elevation_deg
    eligible=(first<=-6)&(final<=-6)
    softened=low*inward_feather(low>0)
    transfer=evidence_tinted_night_material if low_cloud_display=='evidence' else spectral_night_material
    nrgb,na=transfer(t,sw,p,softened,eligible,low_cloud_tint_strength=low_cloud_tint_strength)
    control_nrgb=None
    if colour_control:
        control_nrgb,control_alpha=spectral_night_material(t,sw,p,softened,eligible,low_cloud_tint_strength=low_cloud_tint_strength)
        assert np.array_equal(control_alpha,na)
    # v6 retained the regional low/spectral pass only inside its documented ROI.
    neutral=(.42+.43*np.clip((300-np.where(valid,t,300))/130,0,1))[...,None]*np.ones(3,np.float32)
    nrgb=np.where(inside[...,None],nrgb,neutral)
    na=np.where(valid,na,0)
    expand=lambda v:np.repeat(np.repeat(v,2,0),2,1)
    elevation=expand(e);p1=expand(p)
    cosine=np.maximum(np.sin(np.deg2rad(elevation)),np.sin(np.deg2rad(6)))
    refl=np.where(np.isfinite(raw['B03_fraction_1km'])&(elevation>0),np.maximum(raw['B03_fraction_1km']/cosine,0),0)
    old_ref=np.clip(refl,0,1.2)
    old_a=np.clip(old_ref/1.05,0,1)**.8*p1
    old_c=np.clip(.55+.45*np.sqrt(np.clip(old_ref,0,1)),0,1)
    dc,da=daylight_material(refl,p1)
    j=expand(join);da=old_a*(1-j)+da*j
    dc=np.divide(old_c*old_a*(1-j)+dc*(daylight_material(refl,p1)[1])*j,da,out=np.zeros_like(da),where=da>0)
    factor=np.clip(np.sin(np.deg2rad(elevation))/.25,0,1)
    day=factor**3*(factor*(factor*6-15)+10)
    na,nrgb=expand(na),expand(nrgb)
    alpha=da*day+na*(1-day)
    premult=(dc*da*day)[...,None]+nrgb*(na*(1-day))[...,None]
    rgb=np.divide(premult,alpha[...,None],out=np.zeros_like(premult),where=alpha[...,None]>0)
    if control_nrgb is not None:
        control_premult=(dc*da*day)[...,None]+expand(control_nrgb)*(na*(1-day))[...,None]
        control_rgb=np.divide(control_premult,alpha[...,None],out=np.zeros_like(control_premult),where=alpha[...,None]>0)
        save_unit(dest/'uniform_legacy_colour_rgba.png',np.dstack([control_rgb,alpha]))
        del control_rgb,control_premult,control_nrgb
    # Match production PNG quantization and NativeCloudRenderer.update upload
    # quantization, including harmless float32 C2 overshoot at the endpoints.
    assert np.nanmin(alpha)>=-1e-5 and np.nanmax(alpha)<=1+1e-5
    alpha=np.rint(np.clip(alpha,0,1)*255)/255
    rgb=np.rint(np.clip(rgb,0,1)*255)/255
    uploaded=np.rint(alpha**1.25*255)/255
    day=np.clip(day,0,1)
    rgba=np.dstack([rgb,alpha]);save_unit(dest/'B_current_material_rgba.png',rgba)
    save_unit(dest/'B_current_upload_rgba.png',np.dstack([rgb,uploaded]))
    if not diagnostics:
        if save_layers:
            np.savez_compressed(dest/'material_layers.npz',alpha=alpha,uploaded_alpha=uploaded,day_weight=day,
                                low_confidence=low,probability=p,shortwave_eligible=eligible)
        record={'nominal_utc':stamp.isoformat(),'low_cloud_tint_strength':float(low_cloud_tint_strength),
                'region_policy':region_policy,'low_cloud_display':low_cloud_display,'native_crop_yx':[r0,r1,c0,c1],
                'navigation_max_error_deg':float(max(nav_errors)),'alpha_mean':float(alpha.mean()),
                'uploaded_alpha_mean':float(uploaded.mean()),'day_weight_mean':float(day.mean()),
                'supported_low_native_pixels':int((low>0).sum()),'shortwave_eligible_low_native_pixels':int(((low>0)&eligible).sum())}
        (dest/'material_metadata.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        return record
    # A/B common background is an analysis control, never installed as Earth RGB.
    background=a['official_night_background']
    save_unit(dest/'B_current_flat_preview.png',rgb*uploaded[...,None]+background*(1-uploaded[...,None]))
    ah=a['geo_color_high_clouds_enhanced_alpha'];al=a['geo_color_low_clouds_enhanced_alpha']
    aalpha=ah+(1-ah)*al
    apremult=(a['high_grey']*ah)[...,None]+(al*(1-ah))[...,None]*np.array([.55,.75,.98],np.float32)
    argb=np.divide(apremult,aalpha[...,None],out=np.zeros_like(apremult),where=aalpha[...,None]>0)
    save_unit(dest/'A_official_cloud_stack_rgba.png',np.dstack([argb,aalpha]))
    # Exact official blend formula (at the same Satpy start-time used by its SZA).
    ae=solar_weights(stamp,a['longitude'],a['latitude']).elevation_deg
    aw=np.clip((np.sin(np.deg2rad(ae))-np.cos(np.deg2rad(88)))/(np.cos(np.deg2rad(78))-np.cos(np.deg2rad(88))),0,1)
    av=(1-ah)*al*(1-aw)
    # Include the existing longwave fallback tint; report paired B07 evidence separately.
    bv=expand(softened)*na*(1-day)
    bv_paired=bv*expand(eligible)
    am,bm=av>.05,bv>.05
    disagreement=np.zeros((*am.shape,3),np.float32)
    disagreement[am&~bm]=[1,.25,.1];disagreement[bm&~am]=[.15,.5,1];disagreement[am&bm]=[.2,.9,.4]
    save_unit(dest/'C_low_blue_support.png',disagreement)
    delta=uploaded-aalpha
    save_unit(dest/'C_alpha_difference.png',np.dstack([np.maximum(delta,0),np.zeros_like(delta),np.maximum(-delta,0)]))
    for name,field in [('A_high_alpha',ah),('A_low_alpha',al),('B_alpha',alpha),('B_upload_alpha',uploaded),
                       ('A_day_weight',aw),('B_day_weight',day),('A_effective_blue',av),('B_blue_proxy',bv),
                       ('B_low_evidence',expand(low)),('B_shortwave_eligible',expand(eligible))]:save_unit(dest/(name+'.png'),field)
    np.savez_compressed(dest/'comparison_layers.npz',A_high_alpha=ah,A_low_alpha=al,A_cloud_alpha=aalpha,
                        B_alpha=alpha,B_upload_alpha=uploaded,A_day_weight=aw,B_day_weight=day,
                        A_effective_blue=av,B_blue_proxy=bv,B_low_confidence=expand(low),BTD=expand(t-sw),
                        B_shortwave_eligible=expand(eligible),B_probability=expand(p))
    assert rgba.shape[:2]==tuple(meta['output_shape_yx'])==aalpha.shape
    assert np.isfinite(rgba).all() and ((alpha>=0)&(alpha<=1)).all()
    # Intermediate effects are display quantities, not retrieved cloud fraction or truth.
    record={'nominal_utc':stamp.isoformat(),'grid_shape_yx':list(alpha.shape),'navigation_max_error_deg':float(max(nav_errors)),
            'low_cloud_tint_strength':float(low_cloud_tint_strength),
            'A_blue_proxy_pixels':int(am.sum()),'B_blue_proxy_pixels':int(bm.sum()),
            'B_paired_spectral_blue_proxy_pixels':int((bv_paired>.05).sum()),
            'blue_proxy_intersection_pixels':int((am&bm).sum()),'blue_proxy_union_pixels':int((am|bm).sum()),
            'A_high_alpha_mean':float(ah.mean()),'A_low_alpha_mean':float(al.mean()),
            'A_cloud_alpha_mean':float(aalpha.mean()),'B_material_alpha_mean':float(alpha.mean()),
            'B_uploaded_alpha_mean':float(uploaded.mean()),'A_day_weight_mean':float(aw.mean()),'B_day_weight_mean':float(day.mean()),
            'B_strict_or_partial_low_evidence_native_pixels':int((low>0).sum()),
            'B_supported_low_shortwave_eligible_native_pixels':int(((low>0)&eligible).sum()),
            'B_probability_quality_valid_native_pixels':int(good.sum()),
            'B_retained_original_fixed_roi_yx':[1200,2600,1600,3400],
            'B_scope':'Current native v6 material functions/ROI, 500m->1km mean, confidence join, spectral gate; '
                      'uploaded alpha gamma1.25. Flat diagnostic only, no column-volume/self-shadow/ocean/atmosphere.',
            'blue_metrics_note':'A=(1-high_alpha)*low_alpha*(1-day_weight)>0.05; '
                                'B=softened_low_evidence*night_alpha*(1-day_weight)>0.05, including longwave fallback; '
                                'paired_spectral subset additionally requires both bands solar elevation <= -6 deg; '
                                'not equivalent retrieval definitions, not a cloud-area accuracy score.'}
    (dest/'comparison_metrics.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print('PROJECT AND DIAGNOSTICS',record,flush=True)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stamp',required=True)
    p.add_argument('--project-only',action='store_true')
    args=p.parse_args();stamp=utc_time(args.stamp)
    dest=load_config().processed_dir/'hinnamnor_geocolor_v1'/stamp.strftime('%H%M')
    if not args.project_only:official(stamp,dest)
    if (dest/'l2_observed_roi.npz').exists():project(stamp,dest)


if __name__=='__main__':main()
