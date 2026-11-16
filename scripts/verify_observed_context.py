"""Independent source/support audit, frozen-cloud solar sweep, close comparisons."""
from pathlib import Path
from datetime import timedelta
import json
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt
from ges.catalog import utc_time
from ges.solar import solar_weights
from ges.blend import view_weight,edge_weight
from ges.blend_night import linear_rgb,encode_rgb
from ges.film_transition import load_reference,smoother,layered_pixels,daylight_display
from ges.film_observed import context_pixels

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'data/processed/day_night_v8';p=folder/'earth_day_night.png'
    m=json.loads(p.with_suffix('.json').read_text());stamp=utc_time(m['reference_utc']);w,h=m['width'],m['height']
    out=np.asarray(Image.open(p));base=Path(m['baseline_image']);old=np.asarray(Image.open(base))
    def read(label):return np.asarray(Image.open(p.with_name(p.stem+'_'+label+'.png')))
    cov=read('observation_coverage')>0;refonly=read('static_reference_only')>0;qmap=read('grazing_display_confidence')
    rgbcov=read('observed_rgb_coverage')>0;rgbw=read('observed_rgb_weight')
    assert (out[...,3]==255).all(),'Presentation globe has geometric holes'
    assert not rgbw[~rgbcov].any();np.testing.assert_array_equal(refonly,~cov)
    npth=Path(m['night_image']);nm=m['night_source']
    ircov=np.asarray(Image.open(npth.parent/nm['source_ir_coverage']))>0
    viscov=np.asarray(Image.open(base.with_name(base.stem+'_observed_vis_coverage.png')))>0
    original_rgb_union=np.zeros_like(cov)
    # Independent small samples of the actual RGB source images and actual
    # geostationary weights, not inferred from the output RGB.
    xs=np.arange(0,w,64);ys=np.arange(h//9,8*h//9,96);xx,yy=np.meshgrid(xs,ys)
    lons=-180+(xx+.5)*360/w;lats=90-(yy+.5)*360/w
    numerator=np.zeros(xx.shape+(3,),np.float32);den=np.zeros(xx.shape,np.float32);source_checks=[]
    for record in m['rgb_sources']:
        sp=Path(record['image']);sm=record['provenance'];im=np.asarray(Image.open(sp));scov=im[...,3]>0
        original_rgb_union|=scov
        weight=edge_weight(scov,32)[yy,xx]*view_weight(lons,lats,record['geometry'])
        weight[~scov[yy,xx]]=0;numerator+=linear_rgb(im[yy,xx,:3])*weight[...,None];den+=weight
        source_checks.append({'satellite':sm['satellite'],'actual_scan':[sm['scan_start_utc'],sm['scan_end_utc']],
            'bands':sm['bands'],'quality':sm['quality_policy'],'eligible_rgb_grid_pixels':int(scov.sum())})
    np.testing.assert_array_equal(rgbcov,original_rgb_union)
    np.testing.assert_array_equal(cov,ircov|viscov|original_rgb_union)
    rgb=encode_rgb(np.divide(numerator,den[...,None],out=np.zeros_like(numerator),where=den[...,None]>0))
    selected=rgbw[yy,xx]==255
    sample_error=int(abs(out[yy,xx,:3].astype(int)-rgb.astype(int))[selected].max()) if selected.any() else None
    assert sample_error is not None and sample_error<=2
    dg,_=load_reference(ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',w,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    ng,_=load_reference(ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',w,'static reference night-lights composite, not contemporaneous with satellite clouds')
    ng=np.maximum(ng,(4,5,12)).astype(np.uint8)
    _,dl=daylight_display(np.zeros(xx.shape,np.float32),dg[yy,xx],'sunlit-v1')
    lat=90-(np.arange(h)+.5)*360/w;lon=-180+(np.arange(w)+.5)*360/w
    night_unchanged=0;reference_count=0
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));e=solar_weights(stamp,lon[None,:],lat[sl,None]).elevation_deg
        central=(e<=-12)&(qmap[sl]==255)&(np.abs(lat[sl,None])<50)&ircov[sl]
        if central.any():assert abs(out[sl,...,:3][central].astype(int)-old[sl,...,:3][central].astype(int)).max()<=1
        night_unchanged+=int(central.sum())
        sw=smoother(e,-12,24).astype(np.float32)
        _,daylinear=daylight_display(np.zeros(e.shape,np.float32),dg[sl],'sunlit-v1')
        ground=encode_rgb(daylinear*sw[...,None]+linear_rgb(ng[sl])*(1-sw[...,None]))
        np.testing.assert_array_equal(out[sl,...,:3][refonly[sl]],ground[refonly[sl]])
        reference_count+=int(refonly[sl].sum())
    # Vary solar illumination on the same sampled measurements. Not a weather
    # animation or extra observed time, and not evidence about all seasons.
    a=np.asarray(Image.open(base.with_name(base.stem+'_observed_vis_alpha.png')),np.float32)[yy,xx]/255
    vc=viscov[yy,xx];ic=ircov[yy,xx]
    legacy_conf=smoother(distance_transform_edt(viscov),0,32).astype(np.float32)[yy,xx]
    night=np.asarray(Image.open(npth))[yy,xx]
    q=qmap[yy,xx].astype(np.float32)/255
    # Recover fixed RGB quality separately from the solar factor at this UTC.
    rgb_conf=np.sqrt(edge_weight(rgbcov,64))[yy,xx]
    rgb_conf=smoother(rgb_conf,0,1)
    from ges.blend import view_cosine
    best=np.zeros_like(rgb_conf)
    for record in m['rgb_sources']:
        scov=np.asarray(Image.open(record['image']))[yy,xx,3]>0
        best=np.maximum(best,smoother(view_cosine(lons,lats,record['geometry']),.12,.32)*scov)
    rgb_conf*=best
    previous=None;maximum=0
    for minute in range(-10,11):
        e=solar_weights(stamp+timedelta(minutes=minute),lons,lats).elevation_deg
        legacy,*_=layered_pixels(a,vc,night,ic,dg[yy,xx],ng[yy,xx],e,legacy_conf,'sunlit-v1')
        sw=smoother(e,-12,24).astype(np.float32)
        ground=encode_rgb(dl*sw[...,None]+linear_rgb(ng[yy,xx])*(1-sw[...,None]))
        current=context_pixels(legacy,ground,q,rgb,smoother(e,0,24)*rgb_conf)
        if previous is not None:maximum=max(maximum,int(abs(current[...,:3].astype(int)-previous[...,:3]).max()))
        previous=current
    assert maximum<=12,maximum
    report={'passed':True,'reference_utc':m['reference_utc'],'opaque_surface_is_not_observation_coverage':True,
        'all_observation_union_pixels_checked':int(cov.sum()),'explicit_reference_only_cells':reference_count,
        'central_deep_night_cells_within_one_dn_of_v7':night_unchanged,'actual_rgb_sources':source_checks,
        'frozen_cloud_solar_sweep':{'states':21,'locations':int(xx.size),'max_dn_per_minute':maximum,'not_observed_weather_animation':True},
        'fully_selected_rgb_sample_count':int(selected.sum()),'measured_rgb_sample_max_dn_error':sample_error,
        'limits':'RGB only GOES16/17 at this UTC. Remaining context static/monochrome, not reference-level global measured RGB. No recovered polar clouds, cloud height or independent cloud classification truth.'}
    (folder/'context_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(2560,3*760),(10,14,22));draw=ImageDraw.Draw(sheet)
    for row,name in enumerate(['day_americas_4k.png','terminator_4k.png','sunrise_pacific_4k.png']):
        for col,(path,label) in enumerate([(base.parent,'V7 BEFORE'),(folder,'V8 OBSERVED RGB / STATIC CONTEXT')]):
            im=Image.open(path/'blender'/name).convert('RGB');im.thumbnail((1280,720),Image.Resampling.LANCZOS)
            sheet.paste(im,(col*1280,row*760+40));draw.text((col*1280+10,row*760+12),label,fill='white')
    sheet.save(folder/'observed_context_before_after.png')
    # Full resolution one-camera panels: do not hide seams in a small atlas.
    comparison=Image.new('RGB',(3840,2160),(0,0,0));draw=ImageDraw.Draw(comparison)
    for col,path in enumerate([base.parent,folder]):
        im=Image.open(path/'blender/day_americas_4k.png').convert('RGB')
        # Same pixels in each camera: northeast limb / North Atlantic.
        crop=im.crop((1600,180,2800,1380)).resize((1920,1920),Image.Resampling.LANCZOS)
        comparison.paste(crop,(col*1920,80));draw.text((col*1920+20,24),'V7 BEFORE' if col==0 else 'V8 EDGE / OBSERVED RGB',fill='white')
    comparison.save(folder/'northeast_edge_before_after.png')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
