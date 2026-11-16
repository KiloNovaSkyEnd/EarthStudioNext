"""Offline real-source sampling regression, lossless region and render pairs."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from pyresample.geometry import AreaDefinition

from ges.observed_rgb import rebuild_ahi_rgb
from ges.storage import load_config
from ges.solar import solar_weights
from ges.catalog import utc_time
from scripts.review_observed_day import panel
from scripts.review_observed_twilight import REGIONS, load_source


def render_pairs(cfg, previous, out):
    from ges.observed_day import ObservedDayRenderer
    from ges.film_transition import load_reference
    from ges.solar import sun_direction
    from scripts.review_hinnamnor_ocean import frame, camera
    from scripts.audit_render_baseline import difference, sha

    night, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',13500,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    detail = cfg.processed_dir/'hinnamnor_lights_v1/detail'
    lights = np.load(detail/'east_asia_2016_500m.npy',mmap_mode='r')
    lm = json.loads((detail/'east_asia_2016_500m.json').read_text())
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    root = Path(__file__).resolve().parents[1]
    protected = {str(p.relative_to(root)):sha(p) for p in [root/'ges/goni_film.py',root/'ges/observed_day.py',*list((root/'ges/shaders').glob('*'))] if p.is_file()}
    audit = json.loads((previous/'completion_verification.json').read_text())
    assert sha(root/'ges/observed_day.py') == audit['scripts_sha256']['ges\\observed_day.py']
    previous_hashes = json.loads((previous/'verification.json').read_text())['input_sha256']
    assert all(digest == previous_hashes[str((root/name).resolve())] for name,digest in protected.items())
    # Render implementation and shader files are recorded for independent comparison.
    settings = dict(exposure=1.,city_light_gain=.75,height_scale=.4,thickness=.8,volume_samples=96)
    dest = out/'renders'
    dest.mkdir(exist_ok=False)
    records = dict(settings=settings,render_code_sha256=protected,cases={},
        zero_vis_definition='weight==0 includes night ground AND space background',
        dawn_scope='2200 UTC source RGB only; no corresponding IR/L2 acquired')
    r = ObservedDayRenderer(night,1920,1080,1,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
    try:
        r.set_night_detail(lights,lm['extent_wsen'])
        for stamp in ['0830','1000','1130']:
            rgba,h,nav,meta,_ = frame(stamp,True)
            nav['nominal_utc'] = meta['nominal_utc']
            r.update(rgba,h,nav)
            old,old_meta = load_source(previous,stamp)
            new,new_meta = load_source(out,stamp)
            sun = sun_direction(utc_time(meta['nominal_utc']))
            for name,cam in [('near',camera()),('oblique',camera(True))]:
                r.set_observation(old,np.isfinite(old).all(-1),old_meta)
                a = r.render(cam,sun,**settings)
                r.set_observation(new,np.isfinite(new).all(-1),new_meta)
                b = r.render(cam,sun,**settings)
                weight = r.render(cam,sun,weight_debug=True,float_output=True,**settings)[...,0]
                zero = weight == 0
                parity = difference(a[zero],b[zero]) if zero.any() else None
                if parity:
                    assert parity['max_dn'] == 0,parity
                key = stamp+'_'+name
                panel(dest/(key+'_pair.png'),[a,b],['BEFORE ratio sharpen','AFTER native area mean, no ratio sharpen'])
                Image.fromarray(b).save(dest/(key+'_after.png'))
                records['cases'][key] = dict(delta=difference(a,b),zero_vis_pixels=int(zero.sum()),zero_vis_parity=parity)
                print('RENDER_READY',key,records['cases'][key],flush=True)
    finally:
        r.close()
    assert all(sha(root/p) == h for p,h in protected.items())
    (dest/'verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (dest/'index.html').write_text('<!doctype html><meta charset="utf-8"><style>body{background:#101722;color:white}img{max-width:100%}</style>'
        '<h1>完整场景：左修复前 / 右修复后</h1><p>相同真实UTC、云/IR、太阳、夜光、大气与Airglow。零可见光权重像素逐像素比较。</p>'
        +''.join(f'<p>{key}</p><img src="{key}_pair.png">' for key in records['cases'])
        +'<a href="verification.json">GPU验证记录</a>',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', choices=['0830', '1000', '1130', '2200'])
    parser.add_argument('--render-only', action='store_true')
    args = parser.parse_args()
    cfg = load_config()
    previous = cfg.processed_dir/'observed_twilight_v1'
    out = cfg.processed_dir/'observed_twilight_sampling_v2'
    out.mkdir(exist_ok=True)
    if args.render_only:
        render_pairs(cfg,previous,out)
        return
    if args.prepare:
        _, meta = load_source(previous, args.prepare)
        rgb, _ = rebuild_ahi_rgb(meta, cfg.raw_dir/'reference/satpy_geocolor_v060', out/'sources'/args.prepare)
        print('READY', args.prepare, rgb.shape, flush=True)
        return
    records = {}
    sections = []
    for stamp in ['0830', '1000', '1130', '2200']:
        old, _ = load_source(previous, stamp)
        new, meta = load_source(out, stamp)
        area = AreaDefinition('observed', 'observed', 'geos', meta['projection'], new.shape[1], new.shape[0], meta['area_extent_m'])
        lon, lat = area.get_lonlats()
        elevation = solar_weights(utc_time(meta['nominal_utc']), lon, lat).elevation_deg
        rec = dict(utc=meta['nominal_utc'], regions={},
                   old_finite_pixels=int(np.isfinite(old).all(-1).sum()),
                   new_finite_pixels=int(np.isfinite(new).all(-1).sum()),
                   new_support_outside_old=int((np.isfinite(new).all(-1)&~np.isfinite(old).all(-1)).sum()))
        rec['support_rule'] = 'All contributing raw B01/B02/B03/B04 samples must be finite. Old composite support can be smaller due to old ratio arithmetic; it is not the raw coverage truth.'
        a = np.rint(np.clip(np.nan_to_num(old), 0, 1)*255).astype('uint8')
        b = np.rint(np.clip(np.nan_to_num(new), 0, 1)*255).astype('uint8')
        dest = out/stamp
        dest.mkdir(exist_ok=True)
        for name, (w, e, s, n) in REGIONS.items():
            mask = (lon >= w)&(lon < e)&(lat >= s)&(lat < n)
            yy, xx = np.nonzero(mask)
            if not yy.size:
                continue
            y0,y1,x0,x1 = int(yy.min()),int(yy.max()+1),int(xx.min()),int(xx.max()+1)
            left,right = a[y0:y1,x0:x1],b[y0:y1,x0:x1]
            panel(dest/(name+'_pair.png'), [left,right], [stamp+' UTC | BEFORE ratio sharpen', 'AFTER native area mean, no ratio sharpen'])
            Image.fromarray(right).save(dest/(name+'_after.png'))
            valid = mask&np.isfinite(old).all(-1)&np.isfinite(new).all(-1)
            low = valid&(elevation > 0)&(elevation < 6)
            rec['regions'][name] = dict(crop_yxyx=[y0,y1,x0,x1], common_pixels=int(valid.sum()),
                twilight_pixels=int(low.sum()), new_twilight_all_nonpositive=float((new[low] <= 0).all(-1).mean()) if low.any() else None)
        records[stamp] = rec
        sections.append(f'<h2>2022-08-31 {stamp[:2]}:{stamp[2:]} UTC</h2>'+''.join(
            f'<p>{name}：左修复前 / 右修复后，原像素无损PNG</p><img src="{stamp}/{name}_pair.png">' for name in rec['regions']))
    (out/'verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>晨昏条纹修复 v2</title>'
        '<style>body{background:#101722;color:#ddd;font:17px sans-serif;margin:28px}img{max-width:100%}a{color:#8cf}</style>'
        '<h1>晨昏条纹：移除比例锐化与最近邻抽样</h1><p>保持原始波段、UTC、Rayleigh晨昏处理和单次昼夜交接。'
        '按真实像元面积平均，任一原始贡献像元缺测即保留缺测。没有生成细节、全图模糊、加蓝或改大气。'
        '残余弱光测量噪声仍可能存在；本次没有声称完成传感器条带定标。22:00仅验证源RGB，未取得对应IR/L2。</p>'
        '<p><a href="renders/index.html">完整场景、夜侧一致性验证</a> · <a href="verification.json">源数据与跨区域统计</a></p>'
        +''.join(sections),encoding='utf-8')
    render_pairs(cfg,previous,out)


if __name__ == '__main__':
    main()
