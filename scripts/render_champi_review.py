"""Small current-Champi gallery using unchanged approved limb-v3 renderer."""
import argparse
import json
import time

import numpy as np
from PIL import Image

from ges.atmosphere_scattering import geographic, camera_basis
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.observed_atmosphere import ObservedAtmosphereRenderer
from ges.observed_rgb import _sha
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.prepare_champi_review import write_json

PROTECTED = ['ges/observed_rgb.py', 'ges/observed_day.py', 'ges/observed_atmosphere.py',
             'ges/goni_film.py', 'ges/goni_lowcloud.py', 'ges/cloud_evidence.py',
             'ges/shaders/goni_film.frag']


def camera(lon, lat, altitude, target_lon, target_lat, fov):
    p = geographic(lon, lat, 6371+altitude)
    target = geographic(target_lon, target_lat, 6371)
    up = p/np.linalg.norm(p)
    look = (target-p)/np.linalg.norm(target-p)
    if abs(np.dot(up, look)) > .999:
        up = np.array([0., 0., 1.])
    return dict(position=p, target=target, up=up, fov=fov)


def cases():
    return [
        ('day_disk', '0300', 'full', '日间完整圆盘', dict(position=geographic(140.7, 0., 42164.),
            target=np.zeros(3), up=np.array([0., 0., 1.]), fov=21.)),
        ('day_oblique', '0300', 'full', '日间低轨侧视与大气', camera(123, 12, 800, 134.9, 16.2, 32)),
        ('day_typhoon', '0300', 'detail', '台风日间细节', camera(134.9, 16.2, 2200, 134.9, 16.2, 26)),
        ('twilight_disk', '0830', 'full', '晨昏完整圆盘', dict(position=geographic(140.7, 0., 42164.),
            target=np.zeros(3), up=np.array([0., 0., 1.]), fov=21.)),
        ('twilight_sunward_limb', '0830', 'full', '晨昏地平线与受光大气边缘', camera(161.5, 17, 800, 145, 18, 32)),
        ('night_limb', '1920', 'full', '最新夜间侧视与气辉', camera(117, 15, 800, 131.4, 17.4, 32)),
        ('night_limb_flat', '1920', 'full', '夜侧减弱立体显示（原有开关对照）', camera(117, 15, 800, 131.4, 17.4, 32)),
        ('night_typhoon_detail', '1920', 'detail', '最新台风红外细节', camera(131.4, 17.4, 2200, 131.4, 17.4, 26)),
    ]


def surface_solar_range(cam, sun, width, height):
    right, up, forward = camera_basis(cam['position'], cam['target'], cam['up'])
    yy, xx = np.indices((height, width), dtype=np.float32)
    ray = forward+np.tan(np.deg2rad(cam['fov']/2))*((2*(xx+.5)-width)[..., None]/height*right
        +(height-2*(yy+.5))[..., None]/height*up)
    ray /= np.linalg.norm(ray, axis=-1, keepdims=True)
    origin = np.asarray(cam['position'])
    b = ray@origin
    discriminant = b*b-np.dot(origin, origin)+6371**2
    distance = -b-np.sqrt(np.maximum(discriminant, 0))
    hit = (discriminant >= 0)&(distance > 0)
    normal = (origin+distance[..., None]*ray)/6371
    elevation = np.rad2deg(np.arcsin(np.clip(normal@sun, -1, 1)))[hit]
    return [float(elevation.min()), float(elevation.max())]


def run(selected, width):
    cfg = load_config()
    source = cfg.processed_dir/'champi_20261020_review_v1'
    out = cfg.export_dir/'Champi_20261020_Approved_Review_v1'
    out.mkdir(exist_ok=True)
    hashes = {p: _sha(p) for p in PROTECTED}
    baseline = out/'approved_code_sha256.json'
    if baseline.exists() and json.loads(baseline.read_text()) != hashes:
        raise ValueError('Approved source changed; use a new reviewed output directory')
    if not baseline.exists(): write_json(baseline, hashes)
    night, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg', 8192,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    lights_file = cfg.processed_dir/'hinnamnor_lights_v1/detail/east_asia_2016_500m.npy'
    lights = np.load(lights_file, mmap_mode='r')
    lights_meta = json.loads(lights_file.with_suffix('.json').read_text())
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    records = []
    height = round(width*10/16)
    for name, stamp, scale, title, cam in cases():
        if selected and name not in selected: continue
        dest = out/(name+'.png')
        report = out/(name+'.json')
        if dest.exists() and report.exists():
            rec = json.loads(report.read_text())
            if rec['output_shape_yx'] != [height, width] or rec['camera'] != {k: np.asarray(v).tolist() for k, v in cam.items()}:
                raise ValueError('Cached frame has a different camera or size; retain it and use a new name')
            rec['title'] = title
            write_json(report, rec)
            records.append(rec)
            continue
        folder = source/stamp
        rgb_dir = folder/scale
        rgb_meta = json.loads((rgb_dir/'metadata.json').read_text())
        if _sha(rgb_dir/'rgb.npy') != rgb_meta['rgb_sha256']:
            raise ValueError('RGB cache payload hash mismatch')
        obs = rgb_meta['observation_metadata']
        rgb = np.load(rgb_dir/'rgb.npy', mmap_mode='r')
        clouds = folder if scale == 'full' else rgb_dir
        rgba = np.load(clouds/'night_rgba.npy', mmap_mode='r')
        heights = np.load(clouds/'heights_km.npy', mmap_mode='r')
        ir = np.load(rgb_dir/'ir_support.npy', mmap_mode='r')
        nav = dict(projection=obs['projection'], extent_m=obs['area_extent_m'], nominal_utc=obs['nominal_utc'])
        engine = ObservedAtmosphereRenderer(night, width, height, 2., ocean_mask=water,
            limb_antialias=True, linear_resolve=True)
        started = time.monotonic()
        try:
            engine.set_night_detail(lights, lights_meta['extent_wsen'])
            engine.update(rgba, heights, nav)
            engine.set_observation(rgb, np.isfinite(rgb).all(-1), obs)
            engine.set_ir_support(ir, obs)
            settings = dict(exposure=1., city_light_gain=.75, height_scale=.4, thickness=.8, volume_samples=64)
            if name == 'night_limb_flat':
                settings.update(height_scale=0., volume=False)
            sun = sun_direction(utc_time(obs['nominal_utc']))
            solar_range = surface_solar_range(cam, sun, width, height)
            if stamp == '1920' and solar_range[1] > 0:
                raise ValueError('Night-only observation cannot be used for a daylight camera footprint')
            pixels = engine.render(cam, sun, **settings)
            Image.fromarray(pixels).save(dest)
            # Two bounded controlled ablations, same source/UTC/camera/settings.
            ablations = []
            if name in ['twilight_sunward_limb', 'night_limb']:
                for tag, override in [('no_airglow', dict(airglow=False)),
                                      ('no_atmosphere', dict(atmosphere=False, airglow=False))]:
                    alternate = engine.render(cam, sun, **settings, **override)
                    path = out/(name+'_'+tag+'.png')
                    Image.fromarray(alternate).save(path)
                    diff = np.abs(pixels.astype(float)-alternate.astype(float))
                    ablations.append(dict(file=path.name, mean_abs_dn=float(diff.mean()), max_abs_dn=float(diff.max())))
            rec = dict(name=name, title=title, file=dest.name, nominal_utc=obs['nominal_utc'],
                renderer='ObservedAtmosphereRenderer / approved limb-v3 / native OpenGL, not Blender',
                rgb_profile=obs['photometry_profile'], source_shape_yx=list(rgb.shape[:2]),
                output_shape_yx=list(pixels.shape[:2]), camera={k: np.asarray(v).tolist() for k, v in cam.items()},
                settings=settings, supersample=2, local_limb_rays=16, resolve='linear-light area',
                visible_surface_solar_elevation_degrees=solar_range,
                gpu=engine.device, night_lights='2016 static 500m regional replacement + global fallback',
                ablations=ablations, seconds=time.monotonic()-started,
                limitations='H09 visible hemisphere; real UTC-separated scans; IR is display mapped; atmosphere/Airglow are existing display models; day clouds are reprojected imagery, not a 3D cloud retrieval')
            write_json(report, rec)
            records.append(rec)
            print('RENDERED', name, engine.device, round(rec['seconds'], 1), flush=True)
        finally:
            engine.close()
    for p in out.glob('*.png'):
        with Image.open(p) as im: im.load()
    assert hashes == {p: _sha(p) for p in PROTECTED}, 'Approved renderer was modified'
    write_json(out/'verification.json', dict(approved_code_unchanged=True, frames=records,
        track_source='https://agora.ex.nii.ac.jp/digital-typhoon/summary/wnp/l/202630.html.en',
        status='Rendered for visual inspection; user acceptance pending'))
    notes = {'night_limb': '本帧保留既有检索云高显示；部分云边轮廓明显，未判为通过。下一张保留同源、同机位、大气不变的既有参数对照。',
             'night_limb_flat': '仅 height_scale=0、volume=False；基础薄层仍存在。此图是隔离云高显示问题的对照，不是新的合成配方。'}
    sections = ''.join(f'<section><h2>{r["title"]}</h2><p>{r["nominal_utc"]} · {r["source_shape_yx"][1]} px 源格网</p>'
        +f'<p>{notes.get(r["name"], "")}</p>'
        f'<a href="{r["file"]}"><img src="{r["file"]}"></a><p><a href="{r["name"]}.json">参数和来源</a></p>'
        + ''.join(f'<a href="{a["file"]}">{"关闭气辉" if "no_airglow" in a["file"] else "关闭大气与气辉"}</a> ' for a in r['ablations'])+'</section>' for r in records)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Champi 2026 验收</title>'
        '<style>body{margin:32px auto;max-width:1400px;background:#080c13;color:#dce5ef;font:17px sans-serif}img{width:100%}a{color:#9cd7ff}section{margin:36px 0}</style>'
        '<h1>CHAMPI · 2026-10-20 UTC</h1><p>沿用已确认的原始面积平均 RGB、单次晨昏交接、limb-v3 大气与线性光抗锯齿。</p>'
        '<p>完整圆盘指向日葵可见半球，未伪装成全球多星融合。白天、晨昏、最新夜间是三个不同的真实时刻。'
        '日间细节为1km RGB，圆盘预览为2km RGB，夜间IR为原生2km；这些静帧不宣称原生500m真彩色或Blender已验收。'
        '城市夜光为2016静态参考，大气与气辉沿用既有展示模型。</p>'+sections, encoding='utf-8')
    print('GALLERY', out/'index.html', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='*')
    parser.add_argument('--width', type=int, default=1600)
    args = parser.parse_args()
    run(args.only, args.width)
