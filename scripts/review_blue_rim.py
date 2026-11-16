"""Cache-only camera-motion review of flat clouds and the new display limb."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
import imageio_ffmpeg

from ges.atmosphere_scattering import orbit_camera, camera_basis
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.observed_rgb import _sha
from ges.presentation_earth import PresentationEarthRenderer, PROFILE
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.prepare_champi_review import write_json
from scripts.render_champi_review import cases


def engine(width, supersample):
    cfg = load_config()
    night, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg', 8192,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    renderer = PresentationEarthRenderer(night, width, round(width*10/16), supersample)
    lights = cfg.processed_dir/'hinnamnor_lights_v1/detail/east_asia_2016_500m.npy'
    renderer.set_night_detail(np.load(lights, mmap_mode='r'), json.loads(lights.with_suffix('.json').read_text())['extent_wsen'])
    return renderer


def bind(renderer, stamp, scale):
    root = load_config().processed_dir/'champi_20261020_review_v1'/stamp
    src = root/scale
    record = json.loads((src/'metadata.json').read_text())
    if _sha(src/'rgb.npy') != record['rgb_sha256']: raise ValueError('RGB identity changed')
    meta = record['observation_metadata']
    rgb = np.load(src/'rgb.npy', mmap_mode='r')
    rgba = np.load((root if scale == 'full' else src)/'night_rgba.npy', mmap_mode='r')
    nav = dict(projection=meta['projection'], extent_m=meta['area_extent_m'], nominal_utc=meta['nominal_utc'])
    renderer.update(rgba, None, nav)
    renderer.set_observation(rgb, np.isfinite(rgb).all(-1), meta)
    renderer.set_ir_support(np.load(src/'ir_support.npy'), meta)
    return sun_direction(utc_time(meta['nominal_utc'])), meta


def render(renderer, cam, sun, warm=True, **overrides):
    return renderer.render(cam, sun, city_light_gain=.75, exposure=1., airglow=warm, **overrides)


def stills(preview=False):
    cfg = load_config()
    out = cfg.export_dir/'Champi_Flat_Blue_Rim_v2'
    if preview: out = out/'preview'
    out.mkdir(parents=True, exist_ok=True)
    width = 800 if preview else 1600
    renderer = engine(width, 1 if preview else 2)
    selected = {'day_disk', 'day_oblique', 'night_limb', 'twilight_sunward_limb'} if preview else None
    records = []
    current = None
    try:
        for name, stamp, scale, title, cam in cases():
            if name == 'night_limb_flat' or (selected and name not in selected): continue
            if current != (stamp, scale):
                sun, meta = bind(renderer, stamp, scale)
                current = (stamp, scale)
            path = out/(name+'.png')
            pixels = render(renderer, cam, sun)
            Image.fromarray(pixels).save(path)
            if name == 'night_limb':
                Image.fromarray(render(renderer, cam, sun, warm=False)).save(out/'night_limb_blue_only.png')
            records.append(dict(file=path.name, title=title, utc=meta['nominal_utc'], profile=PROFILE,
                camera={k: np.asarray(v).tolist() for k, v in cam.items()}, shape_yx=list(pixels.shape[:2]),
                clouds='single sphere surface; no height/thickness/normals/shadows/oblique extinction',
                night_rim='art-directed attached warm rim, not physical 90km airglow', source_rgb_sha256=_sha(load_config().processed_dir/f'champi_20261020_review_v1/{stamp}/{scale}/rgb.npy')))
            print('STILL', name, flush=True)
        write_json(out/'stills.json', dict(gpu=renderer.device, frames=records))
    finally: renderer.close()
    return out


def motion():
    out = load_config().export_dir/'Champi_Flat_Blue_Rim_v2'
    out.mkdir(exist_ok=True)
    r = engine(640, 1)
    sun, meta = bind(r, '0830', 'full')
    cams = []
    for t in np.linspace(0, 1, 49):
        smooth = t*t*(3-2*t)
        cam = orbit_camera(111+57*smooth, 17+3*np.sin(np.pi*t), 600+800*np.sin(np.pi*t)**2, 34, heading=-1)
        right, up, forward = camera_basis(cam['position'], cam['target'], cam['up'])
        bank = np.deg2rad(22*np.sin(2*np.pi*t))
        cam['up'] = up*np.cos(bank)+right*np.sin(bank)
        cams.append(cam)
    sequence = cams+cams[-2::-1]
    path = out/'camera_day_night_return.mp4'
    writer = imageio_ffmpeg.write_frames(str(path), (1280, 400), fps=12, codec='libx264',
        pix_fmt_in='rgb24', pix_fmt_out='yuv420p', macro_block_size=2,
        output_params=['-crf','18','-preset','veryfast','-movflags','+faststart'])
    writer.send(None)
    forward_images, max_return_difference, metrics = {}, 0, []
    try:
        for i, cam in enumerate(sequence):
            attached = render(r, cam, sun)
            blue_only = render(r, cam, sun, warm=False)
            if i < len(cams): forward_images[i] = attached
            else:
                paired = len(sequence)-1-i
                delta = int(np.max(abs(attached.astype(int)-forward_images[paired].astype(int))))
                max_return_difference = max(max_return_difference, delta)
            writer.send(np.concatenate([attached, blue_only], axis=1))
            if i in [0, 12, 24, 36, 48]:
                Image.fromarray(attached).save(out/f'motion_{i:03d}.png')
                metrics.append(dict(frame=i, camera={k:np.asarray(v).tolist() for k,v in cam.items()}))
            if i%16 == 0: print('MOTION', i, '/', len(sequence), flush=True)
    finally:
        writer.close()
        gpu = r.device
        r.close()
    if max_return_difference != 0: raise ValueError('Forward/return camera reproducibility failed')
    write_json(out/'motion.json', dict(profile=PROFILE, gpu=gpu, frames=len(sequence), fps=12,
        utc=meta['nominal_utc'], weather='Fixed real 08:30 scan; camera motion only, not weather interpolation or a weather time sequence',
        panels='LEFT attached warm night rim / RIGHT blue day rim only (night glow disabled)',
        motion='Longitude 111..168, altitude600..1400km, ±22deg roll; forward then exact return',
        max_return_difference_dn=max_return_difference, sampled_cameras=metrics, video_sha256=_sha(path)))


def gallery():
    out = load_config().export_dir/'Champi_Flat_Blue_Rim_v2'
    records = json.loads((out/'stills.json').read_text())['frames']
    body = ''.join(f'<h2>{r["title"]}</h2><p>{r["utc"]}</p><a href="{r["file"]}"><img src="{r["file"]}"></a>' for r in records)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>蓝色大气与平面云图验收</title>'
        '<style>body{max-width:1400px;margin:28px auto;background:#090e16;color:#dce6f2;font:18px sans-serif}img,video{width:100%}a{color:#9cf}</style>'
        '<h1>蓝色大气边缘 · 去除云高凸起</h1><p>卫星RGB、IR、原生支持和UTC不变。全部云图映射到同一个球面；不使用云高位移、厚度放大或云高阴影。</p>'
        '<p>蓝色边缘与候选夜光共用世界坐标中的地球轮廓，昼夜按地理太阳高度平滑交接。候选暖色夜光是美术化贴边效果，不宣称90km真实气辉。</p>'
        '<h2>连续运镜：白天→夜晚→白天</h2><p>左：贴边暖色夜光；右：关闭夜光，仅白天蓝色大气。固定08:30真实观测；相机移动、变高度和滚转，无天气补帧。</p>'
        '<video controls loop src="camera_day_night_return.mp4"></video>'+body+
        '<h2>备用方案：关闭夜光</h2><img src="night_limb_blue_only.png"><p>向日葵可见半球；本轮为Native动态验证，尚不代表Blender端已完成。</p>',encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['preview','stills','motion','gallery'])
    mode = parser.parse_args().mode
    if mode in ['preview','stills']: stills(mode == 'preview')
    elif mode == 'motion': motion()
    else: gallery()
