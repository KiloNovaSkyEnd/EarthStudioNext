"""Offline six-stage ocean audit; derived shader only, no downloads/default edits."""
import argparse
import hashlib
import html
import json
import sys
import types
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image, ImageDraw

from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.goni_film import NativeCloudRenderer
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.audit_render_baseline import difference
from scripts.review_hinnamnor_ocean import camera, frame
from scripts.review_hinnamnor_ocean_optics import analysis_class, pair

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def diagnostic_class(out):
    # Reuse the existing bounded Rrs probe, then add isolated inspection taps.
    analysis_class(out)
    path = out / 'ocean_analysis_only.frag'
    shader = path.read_text(encoding='utf-8')
    shader = shader.replace('uniform int ocean_analysis_component;', '''uniform int ocean_analysis_component;
uniform bool audit_linear, audit_hide_clouds;
''')
    shader = shader.replace('float actual_water_weight=0.;', 'float actual_water_weight=0.;vec3 audit_observed=vec3(0.);')
    shader = shader.replace('if(measured.a>.00001)water_diffuse=',
                            'if(measured.a>.00001)audit_observed=measured.rgb/measured.a;\n                if(measured.a>.00001)water_diffuse=')
    shader = shader.replace('        result=mix(result,sea,water);', '''        if(ocean_analysis_component==5)return vec3(water);
        if(ocean_analysis_component==6)return water*day;
        if(ocean_analysis_component==7)return water*audit_observed;
        result=mix(result,sea,water);''')
    shader = shader.replace('if(clouds_enabled&&top.y>first', 'if(!audit_hide_clouds&&clouds_enabled&&top.y>first')
    shader = shader.replace('clamp(srgb(base),0.,1.)', '(audit_linear?base:clamp(srgb(base),0.,1.))')
    path.write_text(shader, encoding='utf-8')
    source = (ROOT / 'ges/goni_film.py').read_text(encoding='utf-8')
    anchor = "(Path(__file__).parent/'shaders/goni_film.frag').read_text()"
    assert source.count(anchor) == 1
    source = source.replace(anchor, 'AUDIT_SHADER')
    module = types.ModuleType('ges._ocean_system_audit')
    module.__package__ = 'ges'
    module.__file__ = str(ROOT / 'ges/goni_film.py')
    module.AUDIT_SHADER = shader
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module.NativeCloudRenderer


def masked_delta(a, b, mask):
    if not mask.any():
        raise ValueError('Empty projected ocean footprint')
    d = b[mask].astype(np.float64) - a[mask]
    luminance = d @ np.array([.2126, .7152, .0722])
    return dict(pixels=int(mask.sum()), mean_absolute_rgb=float(np.abs(d).mean()),
                max_absolute_rgb=float(np.abs(d).max()),
                mean_signed_luminance=float(luminance.mean()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    protected = sorted((ROOT / 'ges').rglob('*.py')) + sorted((ROOT / 'ges/shaders').glob('*'))
    before = {str(p.relative_to(ROOT)): sha(p) for p in protected if p.is_file()}
    cfg = load_config()
    prior = cfg.processed_dir / 'hinnamnor_ocean_research_v2'
    rm = json.loads((prior / 'rrs_probe_metadata.json').read_text())
    raw_path = cfg.raw_dir / 'reference/occci_202208_east_asia_v1/occci_v6_202208_east_asia.nc'
    assert sha(raw_path) == rm['raw_source_sha256']
    raw = np.load(prior / 'rrs_rgb_equivalent_probe.npy', allow_pickle=False)
    day, _ = load_reference(cfg.raw_dir / 'reference/BlueMarble_200410_topography_8km.jpg', 4096,
                           'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night, _ = load_reference(cfg.raw_dir / 'reference/BlackMarble_2016_3km.jpg', 13500,
                             'static reference night-lights composite, not contemporaneous with satellite clouds')
    detail = cfg.processed_dir / 'hinnamnor_lights_v1/detail'
    lights = np.load(detail / 'east_asia_2016_500m.npy', mmap_mode='r')
    lm = json.loads((detail / 'east_asia_2016_500m.json').read_text())
    water = np.asarray(Image.open(cfg.processed_dir / 'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in [raw_path,
              prior / 'rrs_rgb_equivalent_probe.npy', prior / 'rrs_probe_metadata.json']}
    Probe = diagnostic_class(out)
    r = Probe(day, night, 1280, 720, 1, opacity_gamma=1.25, geometry_bridge_pixels=2, ocean_mask=water)
    settings = dict(exposure=1., city_light_gain=.75, height_scale=.4, thickness=.8, volume_samples=96)
    r.set_night_detail(lights, lm['extent_wsen'])
    with r.ctx:
        tex = r.ctx.texture((raw.shape[1], raw.shape[0]), 4, np.ascontiguousarray(raw, np.float32).tobytes(), dtype='f4')
        tex.repeat_x = False
        tex.repeat_y = False
        tex.build_mipmaps()
        tex.anisotropy = 16
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.use(6)
        w, s, e, n = rm['extent_wsen']
        for name, value in dict(actual_water_probe=6, actual_water_enabled=False, ocean_analysis_component=0,
                                audit_linear=False, audit_hide_clouds=False,
                                actual_water_uv=((w+180)/360, (90-n)/180, (e-w)/360, (n-s)/180)).items():
            r.program[name].value = value

    def render(cam, sun, *, component=0, probe=False, linear=False, hide=False, **changes):
        with r.ctx:
            r.program['ocean_analysis_component'].value = component
            r.program['actual_water_enabled'].value = probe
            r.program['audit_linear'].value = linear
            r.program['audit_hide_clouds'].value = hide
        return r.render(cam, sun, **{**settings, **changes}, float_output=linear)

    records = dict(gpu=r.device, settings=settings, inputs=inputs, resolution=[1280, 720], views={})
    sections = []
    cases = {'material': dict(clouds=False, atmosphere=False, airglow=False),
             'ocean_atmosphere': dict(clouds=False, atmosphere=True, airglow=False),
             'ocean_clouds': dict(clouds=True, atmosphere=False, airglow=False),
             'complete': {}, 'shadow_only': dict(hide=True, atmosphere=False, airglow=False),
             'no_reflections': dict(clouds=False, atmosphere=False, airglow=False, ocean_reflections=False),
             'no_airglow': dict(airglow=False), 'no_atmosphere': dict(atmosphere=False)}
    try:
        for stamp in ['0830', '1130']:
            rgba, height, meta, obs, src = frame(stamp, True)
            r.update(rgba, height, meta)
            sun = sun_direction(utc_time(obs['nominal_utc']))
            inputs[str((src / 'official_metadata.json').relative_to(ROOT))] = sha(src / 'official_metadata.json')
            for view in ['near', 'oblique']:
                cam = camera(view == 'oblique')
                key = stamp + '_' + view
                dest = out / key
                dest.mkdir()
                mask = render(cam, sun, component=5, linear=True)[..., 0] > .999
                Image.fromarray(mask.astype(np.uint8)*255).save(dest / 'ocean_footprint.png')
                images, floats = {}, {}
                # Surface taps bypass clouds/path lighting by design, black = masked/unsupported.
                for name, component, probe in [('static_only', 6, False), ('observed_only', 7, True),
                                                ('base_color', 1, False), ('observed_weight', 4, True),
                                                ('diffuse', 2, False), ('reflections', 3, False)]:
                    images[name] = render(cam, sun, component=component, probe=probe, clouds=False)
                    Image.fromarray(images[name]).save(dest / (name + '.png'))
                for name, changes in cases.items():
                    images[name] = render(cam, sun, **changes)
                    Image.fromarray(images[name]).save(dest / (name + '.png'))
                    floats[name] = render(cam, sun, linear=True, **changes)[..., :3]
                    np.save(dest / (name + '_linear.npy'), floats[name], allow_pickle=False)
                candidate = render(cam, sun, probe=True)
                Image.fromarray(candidate).save(dest / 'rrs_probe_complete.png')
                pair(dest / 'before_after.jpg', images['complete'], candidate,
                     'LEFT current / RIGHT real monthly Rrs proxy | same UTC, camera, exposure, clouds, atmosphere')
                # Exact same-context production parity; defaults remain untouched.
                q = NativeCloudRenderer(day, night, 1280, 720, 1, opacity_gamma=1.25, geometry_bridge_pixels=2, ocean_mask=water)
                try:
                    q.set_night_detail(lights, lm['extent_wsen'])
                    q.update(rgba, height, meta)
                    assert q.device == r.device
                    parity = difference(q.render(cam, sun, **settings), images['complete'])
                    assert parity['max_dn'] == 0, parity
                finally:
                    q.close()
                impacts = {}
                for name, a, b in [('atmosphere_clear', 'material', 'ocean_atmosphere'),
                                   ('clouds_total_no_atmosphere', 'material', 'ocean_clouds'),
                                   ('shadow_no_visible_cloud', 'material', 'shadow_only'),
                                   ('visible_cloud_after_shadow', 'shadow_only', 'ocean_clouds'),
                                   ('reflection_clear', 'no_reflections', 'material'),
                                   ('airglow_complete', 'no_airglow', 'complete'),
                                   ('atmosphere_complete', 'no_atmosphere', 'complete')]:
                    impacts[name] = masked_delta(floats[a], floats[b], mask)
                change = difference(images['complete'], candidate)
                if stamp == '1130':
                    assert change['max_dn'] == 0, change
                else:
                    assert change['max_dn'] > 0, change
                records['views'][key] = dict(utc=obs['nominal_utc'], production_parity=parity,
                    probe_difference_display_dn=change, ocean_footprint_linear_impacts=impacts,
                    camera={k: np.asarray(v).tolist() for k, v in cam.items()})
                sheet = Image.new('RGB', (960, 3*298), '#101722')
                draw = ImageDraw.Draw(sheet)
                stages = ['static_only', 'observed_only', 'material', 'ocean_atmosphere', 'ocean_clouds', 'complete']
                for i, name in enumerate(stages):
                    x, y = (i % 2)*480, (i // 2)*298
                    sheet.paste(Image.fromarray(images[name]).resize((480, 270)), (x, y+28))
                    draw.text((x+6, y+6), name, fill='white')
                sheet.save(dest / 'six_stages.jpg')
                sections.append(f'<h2>{key} | {html.escape(obs["nominal_utc"])}</h2>'
                                f'<img src="{key}/six_stages.jpg"><p><a href="{key}/before_after.jpg">同条件前后对照</a> '
                                f'完整图变化 mean={change["mean_dn"]:.4f} / max={change["max_dn"]} DN</p>'
                                + ''.join(f'<a href="{key}/{name}.png">{name}</a> · ' for name in images))
                print('READY', key, change, flush=True)
    finally:
        with r.ctx:
            tex.release()
        r.close()
    assert all(sha(ROOT / p) == digest for p, digest in before.items()), 'Production source changed'
    assert all(sha(ROOT / p) == digest for p, digest in inputs.items()), 'Tracked inputs changed'
    records.update(production_source_sha256=before, production_sources_unchanged=True,
        limits='Ocean footprint = projected geographic water>0.999, includes clouds; NOT observed clear water. '
               'Linear arrays before exposure/display encoding and without clipping. Conditional interventions are not additive causal percentages. '
               'Rrs is 2022-Aug monthly 4km, three-band proxy only; no same-day water/true-color/BRDF claim. '
               'Cloud-free/shadow-only are diagnostic model interventions, not new observations. No downloads.')
    (out / 'verification.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>海洋专项来源审计</title>'
        '<style>body{background:#101722;color:#ddd;font:16px sans-serif;margin:32px}a{color:#8cf}img{max-width:100%}</style>'
        '<h1>海洋来源与六层诊断</h1><p>2022-08-31 08:30 / 11:30 UTC 真实 AHI；海色为2022年8月月合成，'
        '不是台风当天瞬时观测。观测单层图黑色=非海域/无支持，不能解释成黑色海水。'
        '11:30仍可检查原始海色，但显示权重为零。所有关闭云/大气的图仅供诊断；完整场景保持原模型。</p>'
        '<p>六图顺序：静态底图、独立真实海色三波段探针、现有海洋材质、海洋+大气、海洋+云、完整场景。'
        '观测海色单层不含回退；完整探针缺测回退旧底图。使用已验收500m夜光。'
        '<a href="verification.json">线性海域测量与验证</a></p>' + ''.join(sections), encoding='utf-8')


if __name__ == '__main__':
    main()
