"""Prepare bounded observed-day / IR-night fixture, no static daytime ocean."""
import hashlib
import json
import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from ges.catalog import utc_time
from ges.solar import solar_weights, sun_direction

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='blender_orbit_assets_v2')
    args = parser.parse_args()
    out = ROOT/'data/processed'/args.out
    out.mkdir(exist_ok=False)
    paths = [ROOT/'data/processed/day_night_v3/daylight/goes_daylight.png',
             ROOT/'data/processed/day_night_v8/daylight_west/goes_daylight.png',
             ROOT/'data/processed/day_night_v3/transition_global/transition_ir.png',
             ROOT/'data/processed/day_night_v3/transition_global/transition_ir_surface.png',
             ROOT/'data/processed/day_night_v3/transition_global/transition_ir_coverage.png',
             ROOT/'data/processed/day_night_v3/daylight/goes_daylight_view_weight.png',
             ROOT/'data/processed/day_night_v8/daylight_west/goes_daylight_view_weight.png']
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    east,west,night,surface,coverage,east_view,west_view = [np.asarray(Image.open(p)) for p in paths]
    h,w = east.shape[:2]
    assert all(a.shape[:2] == (h,w) for a in (west,night,surface,coverage))
    result = np.zeros((h,w,3),np.uint8)
    day_support = np.zeros((h,w),np.uint8)
    stamp = '2020-10-29T16:40:00Z'
    lon = -180+(np.arange(w)+.5)*360/w
    def linear(x):
        x = x.astype(np.float32)/255
        return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
    for y in range(0,h,128):
        sl = slice(y,min(y+128,h))
        lat = 90-(np.arange(sl.start,sl.stop)+.5)*360/w
        weights = solar_weights(utc_time(stamp),lon[None,:],lat[:,None])
        ea = east[sl,:,3:4]/255.*(east_view[sl,:,None]/255.)
        wa = west[sl,:,3:4]/255.*(west_view[sl,:,None]/255.)
        total = ea+wa
        valid = total>0
        day = (linear(east[sl,:,:3])*ea+linear(west[sl,:,:3])*wa)/np.maximum(total,1.e-6)
        cloud = linear(night[sl,:,:3])
        alpha = night[sl,:,3:4]/255.
        # Static lights/background are a separate night reference. No BlueMarble.
        night_rgb = cloud*alpha+linear(surface[sl,:,:3])*(1-alpha)*weights.city_lights[...,None]
        day_weight = weights.day_cloud[...,None]*np.clip(total,0,1)
        rgb = day*day_weight+night_rgb*(1-day_weight)
        supported = valid | (coverage[sl,:,None]>0)
        rgb = np.where(supported,rgb,0)
        encoded = np.where(rgb<=.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
        result[sl] = np.rint(np.clip(encoded,0,1)*255).astype(np.uint8)
        day_support[sl] = np.where(valid[...,0],255,0)
        if y%512 == 0:
            print('ROWS_READY',y,flush=True)
    texture = out/'observed_day_ir_night.png'
    Image.fromarray(result).save(texture)
    Image.fromarray(day_support).save(out/'day_rgb_support.png')
    meta = dict(utc=stamp, source=str(texture.relative_to(ROOT)).replace('\\','/'),
                sun_direction=sun_direction(utc_time(stamp)).tolist(),
                input_sha256=before, shape=[h,w], static_daytime_ground=False,
                source_limb_policy='Use existing actual-navigation view-confidence weights before IR fallback; never claim missing VIS.',
                daytime='Measured GOES16/17 RGB where supported; source data already 2km product. Gaps use declared IR display.',
                nighttime='Observed IR display and independent static 2016 lights; no live night optical observation.',
                limits='Frozen weather, source scans near nominal UTC; no global RGB or native500m claim. Day support separate.')
    for p in paths:
        assert hashlib.sha256(p.read_bytes()).hexdigest() == before[str(p.relative_to(ROOT))]
    (out/'config.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    print(json.dumps(meta,indent=2))


if __name__ == '__main__':
    main()
