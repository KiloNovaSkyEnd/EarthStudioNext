"""Observed daytime RGB on a continuous, explicitly static reference globe.

Coverage is a separate scientific map. The opaque presentation surface is
never exported as satellite coverage. No spatial cloud reconstruction.
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image
from .film_transition import smoother,load_reference,daylight_display
from .blend import view_cosine,view_weight,edge_weight
from .blend_night import linear_rgb,encode_rgb
from .catalog import utc_time
from .solar import solar_weights

RECIPE='observed-abi-rgb-static-context-v8'


def context_pixels(legacy,ground,confidence,observed_rgb,rgb_weight):
    """Only observed samples affect the reference; exact legacy in good night."""
    q=np.asarray(confidence,dtype=np.float32);w=np.asarray(rgb_weight,dtype=np.float32)
    if not np.isfinite(q).all() or not np.isfinite(w).all() or ((q<0)|(q>1)|(w<0)|(w>1)).any():
        raise ValueError('Finite display confidence/weight in 0..1 required')
    # A reference surface stays geometrically whole even where clouds are
    # unobserved. A missing source must not contribute black texture pixels.
    strength=q*(legacy[...,3].astype(np.float32)/255)
    fallback=np.rint(legacy[...,:3]*strength[...,None]+ground*(1-strength[...,None])).astype(np.uint8)
    rgb=encode_rgb(linear_rgb(observed_rgb)*w[...,None]+linear_rgb(fallback)*(1-w[...,None]))
    rgb[w==0]=fallback[w==0]  # preserve accepted night bytes without roundoff
    return np.dstack([rgb,np.full(q.shape,255,np.uint8)])


def compose_observed(legacy_path,rgb_records,day_reference,night_reference,out):
    legacy_path,out=map(Path,[legacy_path,out]);m=json.loads(legacy_path.with_suffix('.json').read_text())
    stamp=utc_time(m['reference_utc']);w,h=m['width'],m['height']
    if m.get('daylight_profile')!='sunlit-v1':raise ValueError('Verified v7 context input required')
    if not rgb_records:raise ValueError('Actual RGB sources required')
    if out.resolve()==legacy_path.resolve():raise ValueError('Never overwrite baseline')
    legacy=np.asarray(Image.open(legacy_path));lon=-180+(np.arange(w)+.5)*360/w
    dg,dm=load_reference(day_reference,w,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    ng,nm=load_reference(night_reference,w,'static reference night-lights composite, not contemporaneous with satellite clouds')
    ng=np.maximum(ng,(4,5,12)).astype(np.uint8)
    # Best actually observing source, not a geographic latitude cut or current
    # fleet footprint. Grazing display rejection never changes native masks.
    best=np.zeros((h,w),np.float32)
    for source in m['night_source']['sources']:
        p=Path(source['image']);sm=source['provenance'];cov=np.asarray(Image.open(p.parent/sm['source_ir_coverage']))>0
        for row in range(0,h,128):
            sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
            v=view_cosine(lon[None,:],lat[:,None],source['geometry'])
            best[sl]=np.maximum(best[sl],np.where(cov[sl],v,0))
    confidence=smoother(best,.12,.32).astype(np.float32);del best
    numerator=np.zeros((h,w,3),np.float32);den=np.zeros((h,w),np.float32);best=np.zeros_like(den)
    rgb_quality=np.zeros_like(den);dominant=np.zeros((h,w),np.uint8);records=[]
    for index,record in enumerate(rgb_records,1):
        path=Path(record['image']);rm=json.loads(path.with_suffix('.json').read_text());image=np.asarray(Image.open(path))
        if rm.get('product')!='daylight-rgb' or rm.get('display_recipe')!='abi-rayleigh-cold-cloud-log-v2':
            raise ValueError('Verified measured, quality-screened daytime RGB required')
        if image.shape!=(h,w,4) or (rm['width'],rm['height'])!=(w,h):raise ValueError('RGB grid differs')
        if abs((utc_time(rm['scan_start_utc'])-stamp).total_seconds())>1200:raise ValueError('RGB scan >20min from context')
        cov=image[...,3]>0;weight=edge_weight(cov,32)
        for row in range(0,h,128):
            sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
            geometry=record['geometry'];v=view_cosine(lon[None,:],lat[:,None],geometry)
            weight[sl]*=view_weight(lon[None,:],lat[:,None],geometry)
            rgb_quality[sl]=np.maximum(rgb_quality[sl],smoother(v,.12,.32)*cov[sl])
        weight[~cov]=0
        for row in range(0,h,128):
            sl=slice(row,min(row+128,h));numerator[sl]+=linear_rgb(image[sl,...,:3])*weight[sl,...,None]
        den+=weight;wins=weight>best;best[wins]=weight[wins];dominant[wins]=index
        records.append({**record,'provenance':rm})
    rgbcov=den>0;rgb=encode_rgb(np.divide(numerator,den[...,None],out=np.zeros_like(numerator),where=den[...,None]>0))
    del numerator,best
    # Use distance only as a confidence fade within observed support; no image
    # pixels are blurred, filled, extended, or borrowed across a missing pixel.
    # edge_weight wraps the date line, unlike a bare global EDT.
    inward=np.sqrt(edge_weight(rgbcov,64))
    rgb_quality*=smoother(inward,0,1)
    rgba=np.zeros_like(legacy);rgbmap=np.zeros((h,w),np.uint8);groundmap=np.zeros_like(rgbmap)
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        elev=solar_weights(stamp,lon[None,:],lat[:,None]).elevation_deg
        sw=smoother(elev,-12,24).astype(np.float32)
        _,daylinear=daylight_display(np.zeros((sl.stop-sl.start,w),np.float32),dg[sl],'sunlit-v1')
        ground=encode_rgb(daylinear*sw[...,None]+linear_rgb(ng[sl])*(1-sw[...,None]))
        weight=smoother(elev,0,24).astype(np.float32)*rgb_quality[sl]*rgbcov[sl]
        rgba[sl]=context_pixels(legacy[sl],ground,confidence[sl],rgb[sl],weight)
        rgbmap[sl]=np.rint(weight*255).astype(np.uint8);groundmap[sl]=np.rint(sw*255).astype(np.uint8)
    out.parent.mkdir(parents=True,exist_ok=True);Image.fromarray(rgba).save(out)
    maps={'observed_rgb_weight':rgbmap,'observed_rgb_coverage':rgbcov.astype(np.uint8)*255,
          'observed_rgb_source':dominant,'grazing_display_confidence':np.rint(confidence*255).astype(np.uint8),
          'surface_day_weight':groundmap}
    # Observation union remains exactly the old five-source union, separately
    # named and never replaced by this presentation surface's opaque alpha.
    irpath=Path(m['night_image']);irm=m['night_source']
    ircov=np.asarray(Image.open(irpath.parent/irm['source_ir_coverage']))>0
    viscov=np.asarray(Image.open(legacy_path.with_name(legacy_path.stem+'_observed_vis_coverage.png')))>0
    maps['observation_coverage']=(ircov|viscov|rgbcov).astype(np.uint8)*255
    maps['static_reference_only']=np.where(maps['observation_coverage']==0,255,0).astype(np.uint8)
    for label,values in maps.items():Image.fromarray(values).save(out.with_name(out.stem+'_'+label+'.png'))
    meta={**m,'display_recipe':RECIPE,'baseline_image':str(legacy_path.resolve()),'rgb_sources':records,
        'alpha_meaning':'Opaque presentation geometry, NEVER satellite/cloud coverage; use observation_coverage PNG',
        'coverage_map':out.stem+'_observation_coverage.png','reference_only_map':out.stem+'_static_reference_only.png',
        'day_ground_is_contemporaneous':False,'rgb_scope':'GOES16/17 actual C01/C02/C03 with synthetic green; original five-source monochrome/static context elsewhere',
        'grazing_display':'C2 fade of measurement effect to explicitly static ground over best actually observing source view cosine .12.. .32; original masks and RGB unchanged',
        'rgb_transition':'Global C2 solar elevation0..24, inward64px actual RGB support feather, actual view quality; linear RGB crossfade without L2 cloud mask cutting RGB',
        'is_true_color_rgb':False,'static_ground_reference':dm,'static_night_reference':nm,
        'limitations':m['limitations']+' Opaque globe is presentation only; original observational gaps remain explicitly mapped. Observed RGB available only GOES16/17 in this scene, green synthesized. High-latitude clouds are faded for display, not filled or recovered.'}
    out.with_suffix('.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    return out
