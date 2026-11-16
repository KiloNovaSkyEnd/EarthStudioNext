"""Global source/lighting audit; temporal test freezes clouds, varies sun only."""
from pathlib import Path
from datetime import timedelta
import json
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt
from ges.catalog import utc_time
from ges.solar import solar_weights
from ges.film_transition import smoother,layered_pixels,load_reference,CLOUD_CLASSES

ROOT=Path(__file__).resolve().parents[1]


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',default='data/processed/day_night_v6');args=parser.parse_args()
    folder=ROOT/args.out;p=folder/'earth_day_night.png';m=json.loads(p.with_suffix('.json').read_text())
    stamp=utc_time(m['reference_utc']);rgba=np.asarray(Image.open(p));h,w=rgba.shape[:2]
    def read(label):return np.asarray(Image.open(p.with_name(p.stem+'_'+label+'.png')))
    ground=read('surface_day_weight');dw=read('day_contribution');iw=read('night_contribution')
    daycov=read('observed_vis_coverage')>0;dayalpha=read('observed_vis_alpha').astype(np.float32)/255
    npth=Path(m.get('night_image',str(ROOT/'data/processed/day_night_v3/transition_global/transition_ir.png')))
    nm=json.loads(npth.with_suffix('.json').read_text());night=np.asarray(Image.open(npth))
    ircov=np.asarray(Image.open(npth.parent/nm['source_ir_coverage']))>0
    ng,_=load_reference(ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',w,'static reference night-lights composite, not contemporaneous with satellite clouds')
    ng=np.maximum(ng,(4,5,12)).astype(np.uint8)
    na=night[...,3:4].astype(np.float32)/255
    old=np.dstack([np.rint(night[...,:3]*na+ng*(1-na)).astype(np.uint8),ircov.astype(np.uint8)*255])
    lon=-180+(np.arange(w)+.5)*360/w;deep_count=missing_count=0
    regional=[]
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        elev=solar_weights(stamp,lon[None,:],lat[:,None]).elevation_deg
        expected=np.rint(smoother(elev,-12,24).astype(np.float32)*255).astype(np.uint8)
        np.testing.assert_array_equal(ground[sl],expected,err_msg='Ground illumination tied to geographic/sensor edge')
        assert not dw[sl][elev<=0].any()
        assert not dw[sl][~daycov[sl]].any()
        assert not iw[sl][~ircov[sl]].any()
        assert (abs(rgba[sl,...,3].astype(int)-dw[sl].astype(int)-iw[sl].astype(int))<=1).all()
        deep=(elev<=-12)&ircov[sl]
        np.testing.assert_array_equal(rgba[sl][deep],old[sl][deep],err_msg='Accepted deep night changed')
        both=~daycov[sl]&~ircov[sl];assert not rgba[sl][both].any()
        deep_count+=int(deep.sum());missing_count+=int(both.sum())
    source_checks=[]
    for source in m['day_sources']:
        sp=Path(source['image']);sm=source['provenance'];a=np.asarray(Image.open(sp));c=np.asarray(Image.open(sm['class_image']))
        assert not a[~np.isin(c,CLOUD_CLASSES)].any(),'VIS cloud expanded beyond original cloud evidence'
        source_checks.append({'satellite':sm['satellite'],'eligible_grid_pixels':sm['eligible_pixels'],
                              'visible_cloud_grid_pixels':sm['cloud_pixels'],'cloud_labels_not_expanded':True,
                              'actual_scan_utc':[sm['scan_start_utc'],sm['scan_end_utc']]})
    required={'himawari8','goes16','meteosat_msg4','meteosat_msg1'}
    if folder.name in ['day_night_v6','day_night_v7']:required.add('goes17')
    assert {s['satellite'] for s in source_checks}==required
    # Diagnose every longitude and both hemispheres, rather than one camera.
    for south,north in [(-70,-50),(-50,-20),(-20,20),(20,50),(50,70)]:
        lat=90-(np.arange(h)+.5)*360/w;rows=(lat>=south)&(lat<north)
        elev=solar_weights(stamp,lon[None,:],lat[rows,None]).elevation_deg
        band=(elev>0)&(elev<24);eligible=daycov[rows]
        later=solar_weights(stamp+timedelta(minutes=1),lon[None,:],lat[rows,None]).elevation_deg
        sides={}
        for label,rising in [('sunrise',True),('sunset',False)]:
            side=band&((later>elev) if rising else (later<elev))
            sides[label]={'transition_grid_pixels':int(side.sum()),'measured_vis_fraction':float(eligible[side].mean()) if side.any() else None}
        regional.append({'latitude_band':[south,north],'all_longitudes_tested':True,'day_side_transition_grid_pixels':int(band.sum()),
                         'measured_vis_fraction_in_transition':float(eligible[band].mean()) if band.any() else None,'both_terminators':sides})
    # Real sampled cloud fields, 21 UTC lighting states. This is NOT a weather
    # animation or additional satellite acquisitions; source clouds are fixed.
    xs=np.arange(0,w,64);ys=np.arange(h//9,8*h//9,96);xx,yy=np.meshgrid(xs,ys)
    lons=-180+(xx+.5)*360/w;lats=90-(yy+.5)*360/w
    confidence=smoother(distance_transform_edt(daycov),0,32).astype(np.float32)[yy,xx]
    dg,_=load_reference(ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',w,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    ng,_=load_reference(ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',w,'static reference night-lights composite, not contemporaneous with satellite clouds')
    ng=np.maximum(ng,(4,5,12)).astype(np.uint8)
    previous=None;max_change=0;changes=[]
    for minute in range(-10,11):
        elev=solar_weights(stamp+timedelta(minutes=minute),lons,lats).elevation_deg
        out,*_=layered_pixels(dayalpha[yy,xx],daycov[yy,xx],night[yy,xx],ircov[yy,xx],dg[yy,xx],ng[yy,xx],elev,confidence,m.get('daylight_profile','legacy'))
        if previous is not None:
            diff=abs(out[...,:3].astype(int)-previous[...,:3].astype(int));maximum=int(diff.max());max_change=max(max_change,maximum);changes.append(maximum)
        previous=out
    assert max_change<=12,('Abrupt one-minute solar transition',max_change)
    report={'passed':True,'reference_utc':m['reference_utc'],'all_longitudes_independent_surface_lighting':True,
        'deep_night_exact_pixels':deep_count,'both_missing_transparent_pixels':missing_count,'source_checks':source_checks,
        'latitude_transition_checks':regional,'frozen_clouds_solar_sweep':{'utc_start':'2020-10-29T16:30:00Z','utc_end':'2020-10-29T16:50:00Z',
        'states':21,'real_sampled_locations':int(xx.size),'max_rgb_dn_change_per_minute':max_change,'each_step_max_dn':changes,'is_observed_weather_animation':False},
        'is_independent_cloud_truth':False,'limitations':'Global mathematical/source checks and actual 16:40 scene; not all historical times or seasons validated. High-latitude/polar gaps and L2 mask errors remain. Static ground is 2004 reference.'}
    (folder/'global_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(2400,3*715),(10,14,22));draw=ImageDraw.Draw(sheet)
    names=['day_americas_4k.png','sunrise_pacific_4k.png','night_asia_4k.png','indian_ocean_4k.png','terminator_4k.png','south_atlantic_4k.png']
    for i,name in enumerate(names):
        image=Image.open(folder/'blender'/name).convert('RGB');image.thumbnail((1200,675),Image.Resampling.LANCZOS)
        x=(i%2)*1200;y=(i//2)*715;sheet.paste(image,(x,y+40));draw.text((x+12,y+12),name+' / same 2020-10-29 16:40 UTC',fill='white')
    sheet.save(folder/'global_six_views.png');print(json.dumps(report,indent=2),flush=True)
    if folder.name=='day_night_v6':
        comparison=Image.new('RGB',(2400,715),(10,14,22));draw=ImageDraw.Draw(comparison)
        for i,version in enumerate(['day_night_v5','day_night_v6']):
            im=Image.open(ROOT/'data/processed'/version/'blender/sunrise_pacific_4k.png').convert('RGB')
            im.thumbnail((1200,675),Image.Resampling.LANCZOS);comparison.paste(im,(i*1200,40))
            draw.text((i*1200+12,12),version+' / Pacific sunrise / same UTC and camera',fill='white')
        comparison.save(folder/'pacific_west_before_after.png')


if __name__=='__main__':main()
