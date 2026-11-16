"""Remove daytime static Earth entirely in an explicit observed-image mode."""
import argparse
import hashlib
import json
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ges.atmosphere_scattering import geographic
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.goni_film import NativeCloudRenderer, native_project
from ges.observed_day import ObservedDayRenderer
from ges.observed_rgb import rebuild_ahi_rgb
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.audit_render_baseline import difference, sha
from scripts.research_hinnamnor_ocean_source import sample_geo
from scripts.review_hinnamnor_ocean import camera, frame
from scripts.review_hinnamnor_ocean_optics import pair

ROOT = Path(__file__).resolve().parents[1]


def verify_original_native(out):
    """Recreate the byte-exact audited pre-hook class and compare actual scenes."""
    source = (ROOT/'ges/goni_film.py').read_text()
    hook = "    def _fragment_shader(self):\n        return (Path(__file__).parent/'shaders/goni_film.frag').read_text()\n\n"
    assert source.count(hook) == 1
    original = source.replace(hook, '').replace('fragment_shader=self._fragment_shader()',
        "fragment_shader=(Path(__file__).parent/'shaders/goni_film.frag').read_text()")
    previous = json.loads((ROOT/'data/processed/ocean_system_audit_v1/verification.json').read_text())
    # The original file uses CRLF; Path.read_text normalizes it to LF.
    expected = previous['production_source_sha256'][str(Path('ges/goni_film.py'))]
    candidates = [original.encode(), original.replace('\n', '\r\n').encode()]
    assert any(hashlib.sha256(x).hexdigest() == expected for x in candidates), 'Frozen source does not match audited original'
    module = types.ModuleType('ges._before_observed_day')
    module.__package__ = 'ges'
    module.__file__ = str(ROOT/'ges/goni_film.py')
    sys.modules[module.__name__] = module
    exec(compile(original, module.__file__, 'exec'), module.__dict__)
    cfg = load_config()
    day, _ = load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg', 4096,
                           'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg', 13500,
                             'static reference night-lights composite, not contemporaneous with satellite clouds')
    detail = cfg.processed_dir/'hinnamnor_lights_v1/detail'
    lights = np.load(detail/'east_asia_2016_500m.npy', mmap_mode='r')
    lm = json.loads((detail/'east_asia_2016_500m.json').read_text())
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    records = dict(original_native_source_sha256=expected, source_reconstruction_exact=True, scenes={})
    for stamp in ['0830', '1130']:
        rgba, h, meta, obs, _ = frame(stamp, True)
        r = module.NativeCloudRenderer(day, night, 1920, 1080, 1, opacity_gamma=1.25,
                                       geometry_bridge_pixels=2, ocean_mask=water)
        try:
            r.set_night_detail(lights, lm['extent_wsen'])
            r.update(rgba, h, meta)
            for name in ['near', 'oblique']:
                a = r.render(camera(name == 'oblique'), sun_direction(utc_time(obs['nominal_utc'])),
                             exposure=1., city_light_gain=.75, height_scale=.4, thickness=.8, volume_samples=96)
                b = np.asarray(Image.open(out/stamp/(name+'_old.png')).convert('RGB'))
                delta = difference(a, b)
                assert delta['max_dn'] == 0, delta
                records['scenes'][stamp+'_'+name] = dict(gpu=r.device, **delta)
        finally:
            r.close()
    (out/'default_regression.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    return records


def panel(path, arrays, labels):
    height = max(a.shape[0] for a in arrays)
    canvas = Image.new('RGB', (sum(a.shape[1] for a in arrays), height+40), '#101722')
    draw = ImageDraw.Draw(canvas)
    x = 0
    for a, label in zip(arrays, labels):
        canvas.paste(Image.fromarray(a), (x, 40))
        draw.text((x+8, 10), label, fill='white')
        x += a.shape[1]
    canvas.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--photometry', choices=['twilight', 'legacy'], default='twilight',
                        help='Default rebuilds raw AHI RGB with one twilight fade; legacy is an explicit old-source comparison')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cfg = load_config()
    shader_path = ROOT/'ges/shaders/goni_film.frag'
    protected = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT/'ges').rglob('*')
                 if p.is_file() and p.suffix in ['.py', '.frag', '.vert']}
    daypath = cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg'
    day, _ = load_reference(daypath, 4096, 'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg', 13500,
                             'static reference night-lights composite, not contemporaneous with satellite clouds')
    detail = cfg.processed_dir/'hinnamnor_lights_v1/detail'
    lm = json.loads((detail/'east_asia_2016_500m.json').read_text())
    lights = np.load(detail/'east_asia_2016_500m.npy', mmap_mode='r')
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    settings = dict(exposure=1., city_light_gain=.75, height_scale=.4, thickness=.8, volume_samples=96)
    cams = {'near': camera(), 'oblique': camera(True),
            'taiwan_coast': dict(position=geographic(121, 24.5, 7471), target=geographic(121, 24.5, 6371),
                                 up=np.array([0., 0., 1.]), fov=28.)}
    records = dict(inputs={}, source_shaders_sha256=sha(shader_path), settings=settings, frames={}, photometry=args.photometry,
        mode='Observed daytime land+ocean+cloud appearance, not cloud-free surface/volumetric reconstruction',
        daytime_static_map='Not accepted by ObservedDayRenderer. Zero day texture; missing pixels explicitly hatched.',
        limits='AHI source-view apparent RGB reprojected to a sphere. Cloud parallax and arbitrary-view reflection are not reconstructed. '
               'Source already includes cloud/path appearance; no duplicate volume/atmosphere over observed pixels. '
        'Original native path and its physical cloud/atmosphere model remain separately selectable. '
        'Twilight source uses aligned native footprint means without ratio sharpening; legacy source retains its original processing. '
               'Only regional real observations; not global 1km or contemporary observations beneath opaque clouds.')
    sections = []
    for stamp in ['0830', '1000', '1130']:
        rgba, h, meta, obs, src = frame(stamp, True)
        meta['nominal_utc'] = obs['nominal_utc']
        dest = out/stamp
        dest.mkdir()
        source = src/'official_layers.npz'
        records['inputs'][str(source.relative_to(ROOT))] = sha(source)
        records['inputs'][str((src/'official_metadata.json').relative_to(ROOT))] = sha(src/'official_metadata.json')
        # Verify every actually archived raw band against the source manifest.
        for path, digest in obs['input_file_sha256'].items():
            if sha(Path(path)) != digest:
                raise ValueError('AHI raw input SHA mismatch: '+path)
        with np.load(source) as z:
            rgb = z['official_day_rgb']
            valid = np.isfinite(rgb).all(-1)
            lon = z['longitude']
            lat = z['latitude']
        render_meta = obs
        if args.photometry == 'twilight':
            rgb, render_meta = rebuild_ahi_rgb(obs, cfg.raw_dir/'reference/satpy_geocolor_v060', dest/'photometry')
            valid = np.isfinite(rgb).all(-1)
        source_display = np.rint(np.clip(np.nan_to_num(rgb), 0, 1)*255).astype(np.uint8)
        Image.fromarray(source_display).save(dest/'observed_land_ocean_clouds_1km.png')
        Image.fromarray(valid.astype(np.uint8)*255).save(dest/'source_support.png')
        rec = dict(utc=obs['nominal_utc'], source_shape=list(rgb.shape), raw_band_files_verified=len(obs['input_file_sha256']),
                   photometry_profile=render_meta.get('photometry_profile', 'legacy-enhanced-source'),
                   finite_support_pixels=int(valid.sum()), total_source_pixels=int(valid.size), views={})
        records['frames'][stamp] = rec
        if stamp == '0830':
            # Same source grid and footprint: expose the actual map bottleneck.
            x, y = native_project(121., 24.5, meta['projection'])
            xmin, ymin, xmax, ymax = meta['extent_m']
            ix = int((x-xmin)/(xmax-xmin)*rgb.shape[1])
            iy = int((ymax-y)/(ymax-ymin)*rgb.shape[0])
            box = [max(0, ix-320), max(0, iy-320), min(rgb.shape[1], ix+320), min(rgb.shape[0], iy+320)]
            x0, y0, x1, y1 = box
            lo = lon[y0:y1, x0:x1]
            la = lat[y0:y1, x0:x1]
            sampled = sample_geo(day.astype(np.float32)/255, lo, la)
            old = np.rint(np.clip(sampled, 0, 1)*255).astype(np.uint8)
            with Image.open(daypath) as im:
                original_size = list(im.size)
                original = sample_geo(np.asarray(im.convert('RGB'), np.float32)/255, lo, la)
            orig = np.rint(np.clip(original, 0, 1)*255).astype(np.uint8)
            actual = source_display[y0:y1, x0:x1]
            Image.fromarray(old).save(dest/'coast_4096_map_same_grid.png')
            Image.fromarray(orig).save(dest/'coast_original_map_same_grid.png')
            Image.fromarray(actual).save(dest/'coast_observed_1km_native_crop.png')
            panel(dest/'coast_source_comparison.png', [old, orig, actual],
                  ['Old global4096 map', 'Original static map', 'Real AHI1km | same native footprint'])
            rec['coast_diagnostic'] = dict(native_crop_xyxy=box, static_original_shape_wh=original_size,
                current_static_shape_wh=[4096, 2048], source_projected_pixel_m=(xmax-xmin)/rgb.shape[1],
                static_equator_km_per_pixel=2*np.pi*6371/4096,
                warning='Different acquisition dates and cloud content; not a radiometric accuracy comparison. '
                        'No additional sharpening, blur or AI super-resolution; twilight source uses native area means without ratio sharpening. '
                        'Projected1km is not ground1km at every viewing angle.')
        for name, cam in cams.items():
            # Render actual1920/3840 files; neither is a resized 1km source upgrade.
            width, height = (3840, 2160) if name == 'taiwan_coast' else (1920, 1080)
            base = NativeCloudRenderer(day, night, width, height, 1, opacity_gamma=1.25,
                                       geometry_bridge_pixels=2, ocean_mask=water)
            actual = ObservedDayRenderer(night, width, height, 1, opacity_gamma=1.25,
                                         geometry_bridge_pixels=2, ocean_mask=water)
            try:
                for r in [base, actual]:
                    r.set_night_detail(lights, lm['extent_wsen'])
                    r.update(rgba, h, meta)
                actual.set_observation(rgb, valid, render_meta)
                sun = sun_direction(utc_time(obs['nominal_utc']))
                a = base.render(cam, sun, **settings)
                b = actual.render(cam, sun, **settings)
                Image.fromarray(a).save(dest/(name+'_old.png'))
                Image.fromarray(b).save(dest/(name+'_observed.png'))
                pair(dest/(name+'_pair.png'), a, b,
                     'LEFT static ground + model clouds | RIGHT real AHI land+sea+cloud appearance | no static daytime map')
                coverage = actual.render(cam, sun, coverage_debug=True, **settings)
                Image.fromarray(coverage).save(dest/(name+'_coverage.png'))
                rec['views'][name] = dict(gpu=actual.device, resolution=[width, height], difference=difference(a, b))
                # Real night anchor: source replacement must not invent night VIS.
                if stamp == '1130':
                    q = NativeCloudRenderer(np.zeros((2, 4, 3), np.uint8), night, width, height, 1,
                                            opacity_gamma=1.25, geometry_bridge_pixels=2, ocean_mask=water)
                    try:
                        q.set_night_detail(lights, lm['extent_wsen'])
                        q.update(rgba, h, meta)
                        expected = q.render(cam, sun, **settings)
                        weights = actual.render(cam, sun, weight_debug=True, float_output=True, **settings)[..., 0]
                        dark = weights == 0
                        parity = dict(**difference(expected[dark], b[dark]), pixels=int(dark.sum()))
                        assert parity['max_dn'] == 0, 'Night observed RGB leaked into the scene'
                        rec['views'][name]['night_zero_day_native_parity'] = parity
                    finally:
                        q.close()
                print('READY', stamp, name, rec['views'][name], flush=True)
            finally:
                base.close()
                actual.close()
        sections.append(f'<h2>2022-08-31 {stamp[:2]}:{stamp[2:]} UTC</h2>'
                        f'<p><a href="{stamp}/observed_land_ocean_clouds_1km.png">真实卫星原生RGB（陆地/海洋/云）</a> · '
                        f'<a href="{stamp}/taiwan_coast_observed.png">海岸4K</a> · '
                        f'<a href="{stamp}/near_coverage.png">覆盖诊断：绿=日侧有效观测；条纹=缺测；夜侧保留夜景</a></p>'
                        + ''.join(f'<p>{name} 左旧 / 右真实卫星观测</p><a href="{stamp}/{name}_observed.png">'
                                  f'<img src="{stamp}/{name}_pair.png"></a>' for name in cams))
    assert all(sha(ROOT/p) == digest for p, digest in protected.items())
    assert all(sha(ROOT/p) == digest for p, digest in records['inputs'].items())
    records['sources_unchanged_during_render'] = protected
    (out/'verification.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>真实卫星陆地、海洋与云</title>'
        '<style>body{background:#101722;color:#ddd;font:17px sans-serif;margin:28px}img{width:100%;max-width:1920px}a{color:#8cf}</style>'
        '<h1>抛弃固定海陆底图：真实卫星观测视图</h1>'
        '<p>右图白天陆地、海洋和云均来自同一时次AHI近自然RGB。完全不读旧海陆底图；'
        '紫灰条纹明确表示缺测，不能当作海色。没有新下载、造海纹、加蓝或追加锐化；晨昏源使用原生像元面积平均，移除红波段比例锐化。</p>'
        '<p>这是观测影像的球面重投影，不是已完成的物理海洋：云在影像内，不能再叠原三维云和路径光两次。'
        '原三维云/Cloud Relief/大气渲染模式保留在左侧；夜间仍用原实测IR云、已验收夜光和Airglow。'
        '覆盖外没有补全球地图，云下没有假称恢复地表。</p>'
        '<h2>海岸源数据：同投影网格原像素比较</h2><img src="0830/coast_source_comparison.png">'
        '<p>左：当前4096宽底图；中：原始静态底图；右：真实AHI约1km格网。云和拍摄日期不同，不是同日反射率误差评分。</p>'
        + ''.join(sections) + '<p><a href="verification.json">来源、SHA、UTC和验证记录</a></p>', encoding='utf-8')
    verify_original_native(out)


if __name__ == '__main__':
    main()
