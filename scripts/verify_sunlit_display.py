"""Same-source v6/v7 display regression and actual globe comparisons."""
from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw
from ges.solar import solar_weights
from ges.catalog import utc_time

ROOT=Path(__file__).resolve().parents[1]


def main():
    base=ROOT/'data/processed/day_night_v6';folder=ROOT/'data/processed/day_night_v7'
    old=np.asarray(Image.open(base/'earth_day_night.png'));new=np.asarray(Image.open(folder/'earth_day_night.png'))
    meta=json.loads((folder/'earth_day_night.json').read_text());h,w=old.shape[:2]
    np.testing.assert_array_equal(old[...,3],new[...,3])
    for label in ['observed_vis_alpha','observed_vis_coverage','day_contribution','night_contribution','surface_day_weight','visible_source','measured_ir_day_gap']:
        np.testing.assert_array_equal(np.asarray(Image.open(base/('earth_day_night_'+label+'.png'))),
                                      np.asarray(Image.open(folder/('earth_day_night_'+label+'.png'))),err_msg=label)
    lon=-180+(np.arange(w)+.5)*360/w;night_count=day_count=brightened=0;total_delta=0.;old_sum=0.;new_sum=0.
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        elev=solar_weights(utc_time(meta['reference_utc']),lon[None,:],lat[:,None]).elevation_deg
        night=elev<=-12;np.testing.assert_array_equal(old[sl][night],new[sl][night]);night_count+=int(night.sum())
        day=(elev>=24)&(old[sl,...,3]>0)
        a=old[sl,...,:3][day].astype(np.float32);b=new[sl,...,:3][day].astype(np.float32)
        delta=(b-a).mean(axis=-1);assert (delta>=-1).all()
        day_count+=int(day.sum());brightened+=int((delta>1).sum());total_delta+=float(delta.sum())
        old_sum+=float(a.mean(axis=-1).sum());new_sum+=float(b.mean(axis=-1).sum())
    report={'passed':True,'reference_utc':meta['reference_utc'],'unchanged_measured_alpha_masks_source_and_solar_maps':True,
        'all_deep_night_pixels_identical_to_v6':night_count,'fully_day_observed_pixels':day_count,
        'day_pixels_brightened_more_than_1dn':brightened,'day_mean_rgb_dn_before':old_sum/day_count,
        'day_mean_rgb_dn_after':new_sum/day_count,'day_mean_rgb_dn_increase':total_delta/day_count,
        'scope':'Same five-source UTC scene; display brightness only. Static ground, not same-day true RGB; no independent cloud truth.'}
    (folder/'daylight_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    views=['day_americas_4k.png','terminator_4k.png','sunrise_pacific_4k.png']
    sheet=Image.new('RGB',(2400,715*len(views)),(10,14,22));draw=ImageDraw.Draw(sheet)
    for row,name in enumerate(views):
        for col,(path,label) in enumerate([(base,'V6 BEFORE'),(folder,'V7 BRIGHTER DAY')]):
            im=Image.open(path/'blender'/name).convert('RGB');im.thumbnail((1200,675),Image.Resampling.LANCZOS)
            sheet.paste(im,(col*1200,row*715+40));draw.text((col*1200+12,row*715+12),label+' / '+name,fill='white')
    sheet.save(folder/'daylight_before_after.png');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
