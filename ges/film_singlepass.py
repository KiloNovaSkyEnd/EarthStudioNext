"""Single solar handoff of actual daytime RGB to observed IR/night reference.

RGB coverage feather is independent of illumination; it is not another solar
fade. No raw samples, palette, cloud classes or coverage are modified.
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image
from .film_transition import cloud_day_weight,smoother,layered_pixels,load_reference,daylight_display
from .film_observed import context_pixels
from .blend import edge_weight,view_cosine,view_weight
from .blend_night import linear_rgb,encode_rgb
from .solar import solar_weights
from .catalog import utc_time

RECIPE='single-solar-rgb-ir-context-v9'


def single_handoff(day_rgb,night_rgba,night_ground,context,solar_weight,rgb_support):
    """Two complete measured stacks; one solar factor and one support factor."""
    s,q,_=np.broadcast_arrays(np.asarray(solar_weight,np.float32),np.asarray(rgb_support,np.float32),np.empty(context.shape[:-1]))
    if not np.isfinite(s).all() or not np.isfinite(q).all() or ((s<0)|(s>1)|(q<0)|(q>1)).any():
        raise ValueError('Finite solar/support factors in 0..1 required')
    alpha=night_rgba[...,3:4].astype(np.float32)/255
    night=np.rint(night_rgba[...,:3]*alpha+night_ground*(1-alpha)).astype(np.uint8)
    stack=linear_rgb(day_rgb)*s[...,None]+linear_rgb(night)*(1-s[...,None])
    color=encode_rgb(stack*q[...,None]+linear_rgb(context[...,:3])*(1-q[...,None]))
    color[q==0]=context[...,:3][q==0]
    return np.dstack([color,np.full(s.shape,255,np.uint8)])


def compose_singlepass(source_path,out):
    source_path,out=map(Path,[source_path,out]);m=json.loads(source_path.with_suffix('.json').read_text())
    if m['display_recipe']!='observed-abi-rgb-static-context-v8':raise ValueError('Verified v8 provenance required')
    if out.resolve()==source_path.resolve():raise ValueError('Keep prior candidate unchanged')
    w,h=m['width'],m['height'];stamp=utc_time(m['reference_utc']);base=Path(m['baseline_image'])
    def baseline_map(label):return np.asarray(Image.open(base.with_name(base.stem+'_'+label+'.png')))
    a=baseline_map('observed_vis_alpha').astype(np.float32)/255;vc=baseline_map('observed_vis_coverage')>0
    from scipy.ndimage import distance_transform_edt
    visconf=smoother(distance_transform_edt(vc),0,32).astype(np.float32)
    npth=Path(m['night_image']);nm=m['night_source'];night=np.asarray(Image.open(npth))
    ic=np.asarray(Image.open(npth.parent/nm['source_ir_coverage']))>0
    # Input files come from provenance's manifest-independent reference records.
    # Resolve via the project config, not hardcoded machine paths.
    from .storage import load_config
    refs=load_config().raw_dir/'reference'
    dg,_=load_reference(refs/'BlueMarble_200410_topography_8km.jpg',w,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    ng,_=load_reference(refs/'BlackMarble_2016_3km.jpg',w,'static reference night-lights composite, not contemporaneous with satellite clouds')
    ng=np.maximum(ng,(4,5,12)).astype(np.uint8)
    confidence=np.asarray(Image.open(source_path.with_name(source_path.stem+'_grazing_display_confidence.png')),np.float32)/255
    lon=-180+(np.arange(w)+.5)*360/w
    numerator=np.zeros((h,w,3),np.float32);den=np.zeros((h,w),np.float32);quality=np.zeros_like(den)
    best=np.zeros_like(den);dominant=np.zeros((h,w),np.uint8)
    rgbcov=np.zeros((h,w),bool);rgb_records=m['rgb_sources']
    for index,record in enumerate(rgb_records,1):
        p=Path(record['image']);sm=json.loads(p.with_suffix('.json').read_text());im=np.asarray(Image.open(p))
        if sm['product']!='daylight-rgb' or sm['display_recipe']!='abi-rayleigh-cold-cloud-log-v2' or im.shape!=(h,w,4):
            raise ValueError('Matching measured RGB grid and calibrated display required')
        if abs((utc_time(sm['scan_start_utc'])-stamp).total_seconds())>1200:raise ValueError('RGB scan >20min from reference')
        cov=im[...,3]>0;rgbcov|=cov;weight=edge_weight(cov,32)
        for row in range(0,h,128):
            sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
            q=smoother(view_cosine(lon[None,:],lat[:,None],record['geometry']),.12,.32).astype(np.float32)
            # Suppress grazing sources before overlap normalization too, so a
            # poorer view cannot leak through a better source's full confidence.
            weight[sl]*=view_weight(lon[None,:],lat[:,None],record['geometry'])*q
            quality[sl]=np.maximum(quality[sl],q*cov[sl])
            numerator[sl]+=linear_rgb(im[sl,...,:3])*weight[sl,...,None]
        den+=weight;wins=weight>best;best[wins]=weight[wins];dominant[wins]=index
    fused_support=den>0
    rgb=encode_rgb(np.divide(numerator,den[...,None],out=np.zeros_like(numerator),where=den[...,None]>0));del numerator,den,best
    quality*=smoother(np.sqrt(edge_weight(rgbcov,64)),0,1)
    rgba=np.zeros((h,w,4),np.uint8);solar_map=np.zeros((h,w),np.uint8)
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        e=solar_weights(stamp,lon[None,:],lat[:,None]).elevation_deg
        fallback,*_=layered_pixels(a[sl],vc[sl],night[sl],ic[sl],dg[sl],ng[sl],e,visconf[sl],'sunlit-v1','solar-sine-c2')
        sw=smoother(e,-12,24).astype(np.float32)
        _,dl=daylight_display(a[sl],dg[sl],'sunlit-v1')
        ground=encode_rgb(dl*sw[...,None]+linear_rgb(ng[sl])*(1-sw[...,None]))
        context=context_pixels(fallback,ground,confidence[sl],np.zeros_like(ground),np.zeros(e.shape,np.float32))
        solar=cloud_day_weight(e,'solar-sine-c2')
        rgba[sl]=single_handoff(rgb[sl],night[sl],ng[sl],context,solar,quality[sl])
        solar_map[sl]=np.rint(solar*255).astype(np.uint8)
    out.parent.mkdir(parents=True,exist_ok=True);Image.fromarray(rgba).save(out)
    maps={'solar_day_weight':solar_map,'observed_rgb_weight':np.rint(quality*solar_map).astype(np.uint8),
          'observed_rgb_support':np.rint(quality*255).astype(np.uint8),'observed_rgb':np.dstack([rgb,fused_support.astype(np.uint8)*255]),
          'observed_rgb_source':dominant}
    for label in ['observation_coverage','observed_rgb_coverage','grazing_display_confidence','static_reference_only','surface_day_weight']:
        maps[label]=np.asarray(Image.open(source_path.with_name(source_path.stem+'_'+label+'.png')))
    for label,values in maps.items():Image.fromarray(values).save(out.with_name(out.stem+'_'+label+'.png'))
    meta={**m,'display_recipe':RECIPE,'comparison_baseline':str(source_path.resolve()),
        'solar_profile':'solar-sine-c2','solar_handoff':'C2 smootherstep(sin(solar elevation),.1,.3), approximately +5.74..+17.46deg globally',
        'rgb_transition':'One linear RGB solar blend of full observed RGB and measured IR+night reference, then independent actual RGB support feather into monochrome context; no second solar blend',
        'overlap_policy':'Actual coverage/view4/edge weights times source grazing confidence BEFORE normalization',
        'limits_this_revision':'Nonpolar composition only. No polar products fetched; original observation masks and explicit reference-only map retained. No claim of global measured RGB or complete haze removal.'}
    out.with_suffix('.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    return out
