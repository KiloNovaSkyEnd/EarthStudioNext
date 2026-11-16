"""Real sunset/sunrise and multiple geographic regions, identical angle policy."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from pyresample.geometry import AreaDefinition

from ges.atmosphere_scattering import geographic, camera_basis
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.observed_day import ObservedDayRenderer
from ges.solar import solar_weights, sun_direction
from ges.storage import load_config
from scripts.audit_render_baseline import difference, sha
from scripts.research_hinnamnor_ocean_source import sample_geo
from scripts.review_hinnamnor_ocean import camera, frame
from scripts.review_hinnamnor_ocean_optics import pair

ROOT = Path(__file__).resolve().parents[1]
REGIONS = {'china_coast': [113, 118, 21, 26], 'taiwan_strait': [118, 123, 22, 27],
           'east_china_sea': [123, 130, 26, 33], 'south_japan': [129, 135, 29, 35]}


def load_source(out, stamp):
    src = out/'sources'/stamp
    record = json.loads((src/'metadata.json').read_text())
    assert sha(src/'rgb.npy') == record['rgb_sha256']
    return np.load(src/'rgb.npy', mmap_mode='r'), record['observation_metadata']


def solar_bin_stats(old, new, selected, elevation):
    result = {}
    both = selected & np.isfinite(old).all(-1) & np.isfinite(new).all(-1)
    for low, high in [(0, 3), (3, 6), (6, 12), (12, 20), (20, 90)]:
        mask = both & (elevation >= low) & (elevation < high)
        if not mask.any():
            continue
        a, b = old[mask], new[mask]
        result[f'{low}..{high}deg'] = dict(pixels=int(mask.sum()),
            old_all_rgb_nonpositive=float((a <= 0).all(-1).mean()),
            new_all_rgb_nonpositive=float((b <= 0).all(-1).mean()),
            old_display_rgb_median=np.median(np.clip(a, 0, 1), axis=0).tolist(),
            new_display_rgb_median=np.median(np.clip(b, 0, 1), axis=0).tolist())
    return result


def twilight_ocean_footprint(cam, sun, water, width=1920, height=1080):
    right, up, forward = camera_basis(np.asarray(cam['position']), cam['target'], cam['up'])
    yy, xx = np.indices((height, width), dtype=np.float32)
    sx = (2*(xx+.5)-width)/height
    sy = (height-2*(yy+.5))/height
    ray = forward+np.tan(np.deg2rad(cam['fov']/2))*(sx[..., None]*right+sy[..., None]*up)
    ray /= np.linalg.norm(ray, axis=-1, keepdims=True)
    origin = np.asarray(cam['position'])
    b = ray@origin
    det = b*b-np.dot(origin, origin)+6371**2
    t = -b-np.sqrt(np.maximum(det, 0))
    n = (origin+t[..., None]*ray)/6371
    lon = np.rad2deg(np.arctan2(n[..., 1], n[..., 0]))
    lat = np.rad2deg(np.arcsin(np.clip(n[..., 2], -1, 1)))
    mu = n@sun
    return (det >= 0)&(t > 0)&(mu > 0)&(mu < np.sin(np.deg2rad(6)))&(sample_geo(water, lon, lat) > .999)


def main():
    cfg = load_config()
    out = cfg.processed_dir/'observed_twilight_v1'
    dest = out/'review'
    dest.mkdir(exist_ok=False)
    source_files = list((out/'sources').rglob('metadata.json'))+list((out/'sources').rglob('rgb.npy'))
    code = list((ROOT/'ges').rglob('*.py'))+list((ROOT/'ges/shaders').glob('*'))
    protected = {str(p.resolve()): sha(p) for p in source_files+code if p.is_file()}
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'), np.float32)/255
    records = dict(frames={}, renders={}, input_sha256=protected,
                   zero_vis_selection='weight==0: includes night surface AND space background; night_pixels is this legacy counter name, not ground area',
                   scope='Real AHI sunset and sunrise, same angular recipe everywhere. Regional tests are not global/multi-sensor validation.')
    sections = []
    for stamp in ['0830', '1000', '1130', '2200']:
        fixed, meta = load_source(out, stamp)
        if stamp == '2200':
            old, _ = load_source(out, '2200_legacy')
            area = AreaDefinition('real_dawn', 'real dawn', 'geos', meta['projection'], fixed.shape[1], fixed.shape[0], meta['area_extent_m'])
            lon, lat = area.get_lonlats()
            clear = np.ones(fixed.shape[:2], bool)
            classification = 'Geographic sea only; sunrise cloud mask not acquired, not a clear-water proxy'
        else:
            src = cfg.processed_dir/'hinnamnor_geocolor_v1'/stamp
            with np.load(src/'official_layers.npz') as z:
                old = z['official_day_rgb']
                lon, lat = z['longitude'], z['latitude']
            with np.load(src/'l2_observed_roi.npz') as z:
                clear = np.repeat(np.repeat((z['CloudMask'] == 0)&(z['CloudMaskQualFlag'] == 0), 2, 0), 2, 1)
            classification = 'CMSK clear0/QF0 proxy, not cloud-free truth'
        # Same geographic samples for both source versions, no static colour input.
        elevation = solar_weights(utc_time(meta['nominal_utc']), lon, lat).elevation_deg
        sea = sample_geo(water, lon, lat) > .999
        selected = sea & clear
        rec = dict(utc=meta['nominal_utc'], selection=classification,
                   solar_bins=solar_bin_stats(old, fixed, selected, elevation), regions={})
        records['frames'][stamp] = rec
        a = np.rint(np.clip(np.nan_to_num(old), 0, 1)*255).astype(np.uint8)
        b = np.rint(np.clip(np.nan_to_num(fixed), 0, 1)*255).astype(np.uint8)
        directory = dest/stamp
        directory.mkdir()
        Image.fromarray(a).save(directory/'old_source.png')
        Image.fromarray(b).save(directory/'fixed_source.png')
        Image.fromarray(np.rint(np.clip((elevation+6)/26, 0, 1)*255).astype(np.uint8)).save(directory/'solar_elevation_minus6_to20.png')
        for name, (west, east, south, north) in REGIONS.items():
            mask = (lon >= west)&(lon < east)&(lat >= south)&(lat < north)
            yy, xx = np.nonzero(mask)
            if not len(yy):
                continue
            y0, y1, x0, x1 = int(yy.min()), int(yy.max()+1), int(xx.min()), int(xx.max()+1)
            pair(directory/(name+'_source_pair.jpg'), a[y0:y1, x0:x1], b[y0:y1, x0:x1],
                 f'{stamp}UTC {name} | LEFT previous / RIGHT raw-rebuilt, reduced Rayleigh subtraction, single fade owner')
            rec['regions'][name] = dict(native_crop_yxyx=[y0, y1, x0, x1],
                solar_elevation_p01_p50_p99=np.percentile(elevation[mask], [1, 50, 99]).tolist(),
                solar_bins=solar_bin_stats(old, fixed, selected & mask, elevation))
        high = np.isfinite(old).all(-1)&np.isfinite(fixed).all(-1)&(elevation >= 20)
        if high.any():
            delta = np.abs(a[high].astype(int)-b[high])
            rec['high_sun_display_dn'] = dict(pixels=int(high.sum()), mean=float(delta.mean()), max=int(delta.max()))
            assert delta.max() <= 1, rec['high_sun_display_dn']
        if stamp == '1000':
            # Verify the actual failure's low-sun clear-sea proxy, not whole-frame appearance.
            for band in ['0..3deg', '3..6deg']:
                item = rec['solar_bins'][band]
                assert item['new_all_rgb_nonpositive'] < item['old_all_rgb_nonpositive']*.25, item
        sections.append(f'<h2>2022-08-31 {stamp[:2]}:{stamp[2:]} UTC 来源对照</h2><p>{classification}</p>'
            + ''.join(f'<p>{name}</p><img src="review/{stamp}/{name}_source_pair.jpg">' for name in rec['regions']))
        print('SOURCE_VALIDATED', stamp, rec['solar_bins'], flush=True)
        del fixed, old, a, b, lon, lat, elevation, sea, selected, clear

    # Same full scene, cloud inputs, atmosphere, accepted lights and exposure.
    night, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg', 13500,
                             'static reference night-lights composite, not contemporaneous with satellite clouds')
    detail = cfg.processed_dir/'hinnamnor_lights_v1/detail'
    lights = np.load(detail/'east_asia_2016_500m.npy', mmap_mode='r')
    lm = json.loads((detail/'east_asia_2016_500m.json').read_text())
    ocean_mask = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    settings = dict(exposure=1., city_light_gain=.75, height_scale=.4, thickness=.8, volume_samples=96)
    cases = [('0830', 'near', camera()), ('0830', 'oblique', camera(True)),
             ('1000', 'near', camera()), ('1000', 'oblique', camera(True)),
             ('1130', 'near', camera()), ('1130', 'oblique', camera(True))]
    for stamp, name, (lo, la) in [('0830', 'japan', (131., 31.)), ('1000', 'china_coast', (115., 23.)),
                                 ('1000', 'taiwan_transition', (120.5, 24.))]:
        cases.append((stamp, name, dict(position=geographic(lo, la, 7971), target=geographic(lo, la, 6371),
                                       up=np.array([0., 0., 1.]), fov=24.)))
    renders = dest/'renders'
    renders.mkdir()
    r = ObservedDayRenderer(night, 1920, 1080, 1, opacity_gamma=1.25, geometry_bridge_pixels=2, ocean_mask=ocean_mask)
    try:
        r.set_night_detail(lights, lm['extent_wsen'])
        for stamp, name, cam in cases:
            rgba, h, nav, legacy_meta, src = frame(stamp, True)
            nav['nominal_utc'] = legacy_meta['nominal_utc']
            corrected, fixed_meta = load_source(out, stamp)
            with np.load(src/'official_layers.npz') as z:
                original = z['official_day_rgb']
            r.update(rgba, h, nav)
            sun = sun_direction(utc_time(legacy_meta['nominal_utc']))
            r.set_observation(original, np.isfinite(original).all(-1), legacy_meta)
            a = r.render(cam, sun, **settings)
            r.set_observation(corrected, np.isfinite(corrected).all(-1), fixed_meta)
            b = r.render(cam, sun, **settings)
            weight = r.render(cam, sun, weight_debug=True, float_output=True, **settings)[..., 0]
            dark = weight == 0
            parity = difference(a[dark], b[dark]) if dark.any() else None
            if parity:
                assert parity['max_dn'] == 0, parity
            key = stamp+'_'+name
            Image.fromarray(a).save(renders/(key+'_before.png'))
            Image.fromarray(b).save(renders/(key+'_after.png'))
            pair(renders/(key+'_pair.jpg'), a, b, key+' | LEFT previous / RIGHT corrected | same true clouds, sun, lights, exposure')
            records['renders'][key] = dict(delta=difference(a, b), night_pixels=int(dark.sum()), night_parity=parity, gpu=r.device)
            sea = twilight_ocean_footprint(cam, sun, water)
            if sea.any():
                records['renders'][key]['twilight_ocean_display'] = dict(pixels=int(sea.sum()),
                    delta=difference(a[sea], b[sea]),
                    old_near_black_fraction=float((a[sea].max(-1) <= 2).mean()),
                    new_near_black_fraction=float((b[sea].max(-1) <= 2).mean()),
                    selection='Projected geographic water, solar0..6deg, includes clouds; not clear-water radiance')
            print('RENDER_VALIDATED', key, records['renders'][key], flush=True)
        records['settings'] = settings
    finally:
        r.close()
    assert all(sha(p) == digest for p, digest in protected.items())
    (out/'verification.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>晨昏海洋修复与跨区域验证</title>'
        '<style>body{background:#101722;color:#ddd;font:17px sans-serif;margin:28px}img{max-width:100%}a{color:#8cf}</style>'
        '<h1>晨昏发黑修复：原始波段重建与单次淡出</h1>'
        '<p>高天顶角处渐减Rayleigh扣除；去掉源图第二次太阳角淡出；渲染中保留0..6°的一次交接。'
        '规则只看太阳几何，各区域相同。夜海继续暗；不是统一加蓝或提亮。观测视图仍不是自由机位物理海洋。</p>'
        '<p>真实日落：08:30/10:00/11:30 UTC；真实日出：22:00 UTC四波段单分段，只验证源RGB，'
        '未取得该日出时次IR/L2，不能冒称完整三维天气。原夜光、大气、Airglow与云系统保持。</p>'
        '<h2>完整场景前后对照</h2>'
        + ''.join(f'<p>{key}（左旧/右修复）</p><a href="review/renders/{key}_after.png">'
                  f'<img src="review/renders/{key}_pair.jpg"></a>' for key in records['renders'])
        + ''.join(sections)+'<p><a href="verification.json">实际统计与验证</a></p>', encoding='utf-8')


if __name__ == '__main__':
    main()
