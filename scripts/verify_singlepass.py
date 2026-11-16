"""Nonpolar source/seam/solar regressions with explicit polar missing overlay."""
from pathlib import Path
from datetime import timedelta
import json
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt
from ges.catalog import utc_time
from ges.solar import solar_weights
from ges.blend_night import linear_rgb,encode_rgb
from ges.blend import edge_weight,view_weight,view_cosine
from ges.film_transition import load_reference,cloud_day_weight,smoother,layered_pixels,daylight_display
from ges.film_singlepass import single_handoff
from ges.film_observed import context_pixels

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'data/processed/day_night_v9';p=folder/'earth_day_night.png'
    m=json.loads(p.with_suffix('.json').read_text());w,h=m['width'],m['height'];stamp=utc_time(m['reference_utc'])
    baseline=Path(m['comparison_baseline']);old=np.asarray(Image.open(baseline));out=np.asarray(Image.open(p))
    def read(label):return np.asarray(Image.open(p.with_name(p.stem+'_'+label+'.png')))
    coverage=read('observation_coverage')>0;missing=read('static_reference_only')>0
    q=read('observed_rgb_support').astype(np.float32)/255;smap=read('solar_day_weight');rgb=read('observed_rgb')
    source=read('observed_rgb_source');quality=read('grazing_display_confidence')
    for label in ['observation_coverage','static_reference_only','observed_rgb_coverage','grazing_display_confidence']:
        previous=np.asarray(Image.open(baseline.with_name(baseline.stem+'_'+label+'.png')))
        np.testing.assert_array_equal(read(label),previous,err_msg='Observation coverage/polar scope changed: '+label)
    assert not read('observed_rgb_weight')[rgb[...,3]==0].any()
    np.testing.assert_array_equal(missing,~coverage)
    lat=90-(np.arange(h)+.5)*360/w;lon=-180+(np.arange(w)+.5)*360/w
    # Independently recompute sparse fusion from the original two source PNGs,
    # rather than trusting the generated cache or its dominance sidecar.
    tx,ty=np.meshgrid(np.arange(0,w,64),np.where(np.abs(lat)<66.5)[0][::64])
    tlon=-180+(tx+.5)*360/w;tlat=90-(ty+.5)*360/w
    num=np.zeros(tx.shape+(3,),np.float32);den=np.zeros(tx.shape,np.float32)
    best=np.zeros_like(den);winner=np.zeros(tx.shape,np.uint8)
    for index,record in enumerate(m['rgb_sources'],1):
        im=np.asarray(Image.open(record['image']));valid=im[...,3]>0
        weight=edge_weight(valid,32)[ty,tx]*view_weight(tlon,tlat,record['geometry'])
        weight*=smoother(view_cosine(tlon,tlat,record['geometry']),.12,.32).astype(np.float32)
        weight[~valid[ty,tx]]=0;num+=linear_rgb(im[ty,tx,:3])*weight[...,None];den+=weight
        wins=weight>best;best[wins]=weight[wins];winner[wins]=index
    expected_rgb=encode_rgb(np.divide(num,den[...,None],out=np.zeros_like(num),where=den[...,None]>0))
    np.testing.assert_array_equal(rgb[ty,tx,:3],expected_rgb)
    np.testing.assert_array_equal(rgb[ty,tx,3]>0,den>0)
    np.testing.assert_array_equal(source[ty,tx],winner)
    central_night=0;selected_rgb=0;regional=[]
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));e=solar_weights(stamp,lon[None,:],lat[sl,None]).elevation_deg
        expected=cloud_day_weight(e,'solar-sine-c2')
        np.testing.assert_array_equal(smap[sl],np.rint(expected*255).astype(np.uint8))
        night=(e<=-12)&(quality[sl]==255)&(np.abs(lat[sl,None])<50)&coverage[sl]
        if night.any():assert abs(out[sl,...,:3][night].astype(int)-old[sl,...,:3][night].astype(int)).max()<=1
        central_night+=int(night.sum())
        full=(expected==1)&(q[sl]==1)&(np.abs(lat[sl,None])<66.5)
        if full.any():assert abs(out[sl,...,:3][full].astype(int)-rgb[sl,...,:3][full].astype(int)).max()<=1
        selected_rgb+=int(full.sum())
    # Inspect actual dayRGB sensor seams, separately from coast/cloud edges.
    # A display seam test is not evidence of radiometric/calibrated fusion.
    nonpolar=np.abs(lat[:,None])<66.5
    seam=(source[:,1:]!=source[:,:-1])&(source[:,1:]>0)&(source[:,:-1]>0)
    seam&=(q[:,1:]==1)&(q[:,:-1]==1)&(smap[:,1:]==255)&(smap[:,:-1]==255)&nonpolar
    seam_stats={}
    for label,im in [('before',old),('after',out)]:
        delta=abs(im[:,1:,:3].astype(np.int16)-im[:,:-1,:3].astype(np.int16)).max(axis=-1)[seam]
        seam_stats[label]={'samples':int(delta.size),'median_dn':float(np.median(delta)) if delta.size else None,
                           'p95_dn':float(np.quantile(delta,.95)) if delta.size else None,'max_dn':int(delta.max()) if delta.size else None}
    if seam.any():assert seam_stats['after']['p95_dn']<=seam_stats['before']['p95_dn']+5
    for west,east,south,north,name in [(-180,-110,-55,55,'Pacific West'),(-110,-30,-55,55,'Americas'),
        (-30,40,-55,60,'Atlantic Europe Africa'),(40,100,-55,55,'Indian Ocean'),(100,180,-55,55,'Asia Pacific East')]:
        rows=(lat>=south)&(lat<=north);cols=(lon>=west)&(lon<=east)
        lo,la=np.meshgrid(lon[cols],lat[rows]);e=solar_weights(stamp,lo,la).elevation_deg
        later=solar_weights(stamp+timedelta(minutes=1),lo,la).elevation_deg
        band=(e>5.739)&(e<17.458);c=coverage[np.ix_(rows,cols)]
        regional.append({'region':name,'observed_cells':int(c.sum()),'day_side_twilight_cells':int((band&c).sum()),
                         'sunrise_cells':int((band&c&(later>e)).sum()),'sunset_cells':int((band&c&(later<e)).sum())})
    # Independent solar sweep over cached actual measured pixels. Clouds stay
    # frozen: no claim of observations from these additional lighting states.
    xs=np.arange(0,w,64);ys=np.where(np.abs(lat)<66.5)[0][::64];xx,yy=np.meshgrid(xs,ys)
    lo=-180+(xx+.5)*360/w;la=90-(yy+.5)*360/w
    base=Path(m['baseline_image']);npth=Path(m['night_image']);nm=m['night_source']
    a=np.asarray(Image.open(base.with_name(base.stem+'_observed_vis_alpha.png')),np.float32)/255
    vc=np.asarray(Image.open(base.with_name(base.stem+'_observed_vis_coverage.png')))>0
    visconf=smoother(distance_transform_edt(vc),0,32).astype(np.float32)[yy,xx];a=a[yy,xx];vc=vc[yy,xx]
    night=np.asarray(Image.open(npth))[yy,xx];ic=np.asarray(Image.open(npth.parent/nm['source_ir_coverage']))[yy,xx]>0
    dg,_=load_reference(ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',w,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    ng,_=load_reference(ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',w,'static reference night-lights composite, not contemporaneous with satellite clouds')
    dg=dg[yy,xx];ng=np.maximum(ng[yy,xx],(4,5,12)).astype(np.uint8)
    prev=None;maximum=0
    for minute in range(-10,11):
        e=solar_weights(stamp+timedelta(minutes=minute),lo,la).elevation_deg
        legacy,*_=layered_pixels(a,vc,night,ic,dg,ng,e,visconf,'sunlit-v1','solar-sine-c2')
        _,dl=daylight_display(a,dg,'sunlit-v1');sw=smoother(e,-12,24).astype(np.float32)
        ground=encode_rgb(dl*sw[...,None]+linear_rgb(ng)*(1-sw[...,None]))
        context=context_pixels(legacy,ground,quality[yy,xx].astype(np.float32)/255,np.zeros_like(dg),np.zeros(e.shape,np.float32))
        current=single_handoff(rgb[yy,xx,:3],night,ng,context,cloud_day_weight(e,'solar-sine-c2'),q[yy,xx])
        if prev is not None:maximum=max(maximum,int(abs(current[...,:3].astype(int)-prev[...,:3]).max()))
        prev=current
    assert maximum<=12,maximum
    report={'passed':True,'reference_utc':m['reference_utc'],'scope':'nonpolar display only; no polar acquisitions',
        'all_source_coverage_and_polar_missing_masks_unchanged':True,'explicit_reference_only_cells':int(missing.sum()),
        'central_night_cells_within_one_dn_of_v8':central_night,'nonpolar_fully_selected_measured_rgb_cells':selected_rgb,
        'independent_original_rgb_and_dominance_samples_exact':int(tx.size),
        'observed_rgb_overlap_seams':seam_stats,'regional_day_side_twilight':regional,
        'frozen_cloud_solar_sweep':{'states':21,'locations':int(xx.size),'maximum_dn_per_minute':maximum,'not_weather_observations':True},
        'limitations':'RGB scope still GOES16/17. Fixed scene and synthetic lighting sweep do not validate all historical acquisitions. Static context/IR classifications/limb scattering and scan differences remain.'}
    (folder/'singlepass_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    # Large same-camera crops, not only small atlas views.
    sheet=Image.new('RGB',(2560,2280),(10,14,22));draw=ImageDraw.Draw(sheet)
    for row,name in enumerate(['terminator_4k.png','sunrise_pacific_4k.png','day_americas_4k.png']):
        for col,(path,label) in enumerate([(baseline.parent,'V8 BEFORE'),(folder,'V9 SINGLE SOLAR HANDOFF')]):
            im=Image.open(path/'blender'/name).convert('RGB').crop((960,120,2880,2040))
            im.thumbnail((720,720),Image.Resampling.LANCZOS);sheet.paste(im,(col*1280+280,row*760+40))
            draw.text((col*1280+20,row*760+12),label+' / '+name,fill='white')
    sheet.save(folder/'nonpolar_before_after.png')
    im=Image.open(p).convert('RGB').resize((2048,1024),Image.Resampling.LANCZOS)
    mask=Image.fromarray(missing.astype(np.uint8)*255).resize(im.size,Image.Resampling.NEAREST)
    inspection=Image.new('RGB',(2048,1080),(10,14,22));inspection.paste(im,(0,56))
    overlay=np.asarray(im).copy();yy2,xx2=np.indices((1024,2048));no=np.asarray(mask)>0
    overlay[no&((xx2+yy2)%16<5)]=(210,60,180)
    inspection.paste(Image.fromarray(overlay),(0,56));d=ImageDraw.Draw(inspection)
    d.text((16,16),'MAGENTA HATCH = NO CURRENT OBSERVATION / STATIC GROUND ONLY. POLAR CLOUDS NOT FILLED.',fill='white')
    inspection.save(folder/'coverage_inspection.png')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
