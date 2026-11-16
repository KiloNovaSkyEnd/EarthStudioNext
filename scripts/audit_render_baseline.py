"""Offline audit only: freeze existing materials, render controls, never overwrite.

Run with --out NEW_DIRECTORY; optionally --compare PREVIOUS_DIRECTORY.
No source preparation, downloads, visual recipes or production defaults change.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw
from ges.storage import load_config
from ges.atmosphere_scattering import ScatteringRenderer, geographic
from ges.goni_film import NativeCloudRenderer
from ges.film_transition import load_reference
from ges.catalog import utc_time
from ges.solar import sun_direction
from scripts.build_goni_film import cameras


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def difference(a, b):
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return {'mean_dn': float(d.mean()), 'max_dn': int(d.max()),
            'changed_pixels': int(np.any(d != 0, axis=-1).sum())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    cfg = load_config()
    inputs, outputs, checks, views = {}, {}, {}, {}
    root = Path(__file__).resolve().parent.parent

    def track(path):
        path = Path(path).resolve()
        inputs[str(path)] = sha(path)
        return path

    def read_json(path):
        return json.loads(track(path).read_text(encoding='utf-8'))

    def image(path, mode):
        with Image.open(track(path)) as im:
            return np.asarray(im.convert(mode)).copy()

    def save(name, pixels):
        Image.fromarray(pixels).save(args.out / (name + '.png'))
        outputs[name] = sha(args.out / (name + '.png'))

    def pair(name, on, off):
        checks[name] = difference(on, off)
        assert checks[name]['max_dn'] > 0, name + ' has no rendered contribution'
        sheet = Image.new('RGB', (1280, 388), (8, 12, 18))
        sheet.paste(Image.fromarray(off), (0, 28))
        sheet.paste(Image.fromarray(on), (640, 28))
        ImageDraw.Draw(sheet).text((10, 8), name + ' | LEFT control / RIGHT enabled', fill='white')
        save(name + '_pair', np.asarray(sheet))

    for folder in ['ges', 'scripts']:
        for path in sorted((root / folder).rglob('*')):
            if path.suffix in {'.py', '.frag'} and '__pycache__' not in path.parts:
                track(path)
    day_path = track(cfg.raw_dir / 'reference/BlueMarble_200410_topography_8km.jpg')
    night_path = track(cfg.raw_dir / 'reference/BlackMarble_2016_3km.jpg')
    track(day_path.with_suffix('.json')); track(night_path.with_suffix('.json'))
    day, _ = load_reference(day_path, 4096, 'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night, _ = load_reference(night_path, 4096, 'static reference night-lights composite, not contemporaneous with satellite clouds')
    water = image(cfg.processed_dir / 'cloud_relief_v4/static_ocean_mask.png', 'L')
    v4 = read_json(cfg.processed_dir / 'cloud_relief_v4/verification.json')
    folder = cfg.processed_dir / 'cloud_relief_v1/goes17_1640'
    ground = image(folder / 'static_ground.png', 'RGB')
    cloud = image(cfg.processed_dir / 'cloud_relief_v4/independent_cloud_8192.png', 'RGBA')
    with np.load(track(folder / 'retrieved_height.npz')) as data:
        heights = data['height_km'].copy()
    for name in ['height_support.png', 'observation_coverage.png', 'provenance.json']:
        track(folder / name)
    for path in v4['cloud_full_grid']['input_sha256_unchanged']:
        track(path)
    engine = ScatteringRenderer([ground, day, night], 640, 360, supersample=1.5,
                                cloud_layer=(cloud, heights), ocean_mask=water)
    gpu = engine.device
    settings = dict(steps=96, sun_steps=20, relief_strength=.4,
                    night_depth_strength=1., stable_cloud_sampling=True,
                    ocean_material=True, airglow=True, exposure=2.)
    try:
        for record in v4['samples'][:2]:
            name = 'global_' + record['view']
            camera = {k: np.asarray(v) if k != 'fov' else v for k, v in record['camera'].items()}
            sun = sun_direction(utc_time(record['actual_scan_start_utc']))
            on = engine.render(camera, sun, **settings)
            assert np.array_equal(on, engine.render(camera, sun, **settings)), 'repeat mismatch'
            save(name, on)
            views[name] = {'camera': record['camera'], 'sun': sun.tolist(),
                           'utc': record['actual_scan_start_utc'], 'settings': settings}
            for component, override in [('atmosphere', {'enabled': False}),
                                        ('airglow', {'airglow': False}),
                                        ('ocean', {'ocean_material': False}),
                                        ('relief', {'relief_strength': 0.})]:
                off = engine.render(camera, sun, **{**settings, **override})
                save(name + '_no_' + component, off)
                pair(name + '_' + component, on, off)
    finally:
        engine.close()

    # Cloud-free diagnostic controls isolate actual static lights and UTC sun.
    # They are explicitly NOT clear-sky observations or new cloud products.
    camera = {'position': geographic(120, 25, 11000), 'target': np.zeros(3),
              'up': np.array([0., 0., 1.]), 'fov': 80}
    sun = sun_direction(utc_time('2020-10-30T14:00:00Z'))
    clear = ScatteringRenderer([ground, day, night], 640, 360, ocean_mask=water)
    dark = ScatteringRenderer([ground, day, np.zeros_like(night)], 640, 360, ocean_mask=water)
    try:
        on = clear.render(camera, sun, enabled=False, dynamic=True)
        off = dark.render(camera, sun, enabled=False, dynamic=True)
        save('static_lights_on', on); save('static_lights_off', off)
        pair('static_city_lights', on, off)
        other = clear.render(camera, -sun, enabled=False, dynamic=True)
        save('diagnostic_reversed_sun', other)
        pair('diagnostic_solar_response', other, on)
        views['static_lights'] = {'camera': {k: np.asarray(v).tolist() for k,v in camera.items()},
                                 'sun': sun.tolist(), 'utc': '2020-10-30T14:00:00Z',
                                 'synthetic_control': 'cloud layer disabled; reversed sun only in labelled control'}
    finally:
        dark.close(); clear.close()

    # Native Goni: real day/night endpoints, three existing 3D camera presets.
    engine = NativeCloudRenderer(day, night, 640, 360, supersample=1.25,
                                 opacity_gamma=1.25, geometry_bridge_pixels=2, ocean_mask=water)
    native_settings = dict(volume=True, atmosphere=True, airglow=True,
                           height_scale=.4, thickness=.8, volume_samples=96)
    try:
        for stamp in ['20201030T0400Z', '20201030T1400Z']:
            folder = cfg.processed_dir / 'goni_film_v1/frames' / stamp
            meta = read_json(folder / 'frame.json')
            track(meta['source_manifest'])
            rgba = image(folder / meta.get('render_material_file', 'cloud.png'), 'RGBA')
            with np.load(track(folder / 'height.npz')) as data:
                height = data['height_km'].copy()
            engine.update(rgba, height, meta)
            sun = sun_direction(utc_time(meta['nominal_utc']))
            for label, camera in cameras().items():
                name = 'goni_' + stamp + '_' + label
                on = engine.render(camera, sun, **native_settings)
                assert np.array_equal(on, engine.render(camera, sun, **native_settings)), 'native repeat mismatch'
                save(name, on)
                views[name] = {'camera': {k: np.asarray(v).tolist() for k,v in camera.items()},
                               'sun': sun.tolist(), 'nominal_utc': meta['nominal_utc'],
                               'scan_start_utc': meta['scan_start_utc'], 'scan_end_utc': meta['scan_end_utc'],
                               'material_revision': meta['material_revision'], 'settings': native_settings}
                if label == 'oblique':
                    for component, override in [('atmosphere', {'atmosphere': False}),
                                                ('airglow', {'airglow': False}),
                                                ('volume', {'volume': False})]:
                        off = engine.render(camera, sun, **{**native_settings, **override})
                        save(name + '_no_' + component, off)
                        # Daytime glow may legitimately be zero; record rather than force it.
                        if component == 'airglow' and stamp.endswith('0400Z'):
                            checks[name + '_' + component] = difference(on, off)
                        else:
                            pair(name + '_' + component, on, off)
    finally:
        engine.close()
    assert all(sha(p) == value for p, value in inputs.items()), 'Input changed during audit'
    comparison = None
    if args.compare:
        previous = json.loads((args.compare / 'verification.json').read_text())
        comparison = {name: difference(np.asarray(Image.open(args.out / (name+'.png'))),
                                      np.asarray(Image.open(args.compare / (name+'.png')))) for name in outputs}
        assert previous['input_sha256'] == inputs, 'Frozen input manifest changed'
        assert all(d['max_dn'] == 0 for d in comparison.values()), 'Baseline pixel regression'
    packages = {name: importlib.metadata.version(name) for name in
                ['numpy', 'Pillow', 'moderngl', 'glcontext', 'pyorbital', 'pyproj']}
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'gpu': gpu,
              'python': sys.version, 'platform': platform.platform(), 'packages': packages,
              'resolution': [640,360], 'input_sha256': inputs, 'output_sha256': outputs,
              'views': views, 'component_differences': checks, 'repeat_exact': True,
              'comparison': comparison,
              'limits': 'Static rendered baseline, not temporal weather stability or visual acceptance. '
                        'Day/night endpoints and two real sunrise camera views only. '
                        '640x360 audit outputs; existing HD/films retained. No new downloads. '
                        'Static references are not 2020 satellite observations; no Hinnamnor acquisition.'}
    (args.out / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    html = '<meta charset="utf-8"><title>Audit baseline</title><style>body{background:#0b1019;color:white;font:16px system-ui}img{max-width:100%}</style>'
    html += '<h1>Frozen render baseline</h1><p>UTC and provenance: verification.json. Controls are diagnostics, not new observations.</p>'
    for name in outputs:
        if name.endswith('_pair'):
            html += '<h2>'+name+'</h2><img src="'+name+'.png">'
    (args.out / 'index.html').write_text(html, encoding='utf-8')
    print('PASS', len(outputs), 'images;', len(checks), 'controls;', gpu, flush=True)


if __name__ == '__main__':
    main()
