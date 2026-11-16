"""Explicitly approximate night display, derived from measured IR and static lights.

The opacity curve is an artistic transfer function, NOT cloud detection,
optical thickness, or a cloud-height retrieval. Coverage is stored separately.
"""
import json
from pathlib import Path
import warnings

import numpy as np
from PIL import Image

from .catalog import utc_time
from .render import IR_GRAY_RECIPE
from .solar import global_solar_weights


def night_cloud_rgba(kelvin, coverage, warm_k=293.15, cold_k=193.15, gamma=1.3):
    """Cold-white display with warm-background suppression; not a cloud mask."""
    if not all(np.isfinite(v) for v in [warm_k,cold_k,gamma]) or warm_k <= cold_k or gamma <= 0:
        raise ValueError('Finite warm > cold temperature and positive gamma required')
    values = np.asarray(kelvin, dtype=np.float32)
    valid = np.asarray(coverage, dtype=bool)
    if values.shape != valid.shape:
        raise ValueError('IR and genuine coverage dimensions differ')
    valid = valid & np.isfinite(values) & (values >= 100) & (values <= 350)
    safe = np.where(valid, values, warm_k)
    opacity = np.clip((warm_k - safe) / (warm_k - cold_k), 0, 1) ** gamma
    rgba = np.empty(values.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = (218, 222, 230)
    rgba[..., 3] = np.where(valid, np.rint(opacity * 255), 0).astype(np.uint8)
    return rgba


def prepare_night_display(source: Path, lights: Path, out_dir: Path) -> Path:
    meta = json.loads(source.with_suffix('.json').read_text(encoding='utf-8'))
    reference = json.loads(lights.with_suffix('.json').read_text(encoding='utf-8'))
    if (meta.get('product') != 'ir-gray' or meta.get('display_recipe') != IR_GRAY_RECIPE
            or meta.get('display_mapping') != {'cold_white_c':-100,'warm_black_c':45}
            or meta.get('projection') != 'EPSG:4326'
            or meta.get('extent_wsen') != [-180,-90,180,90]):
        raise ValueError('Night display requires corrected cold-white global IR with known mapping')
    if (reference.get('projection') != 'EPSG:4326'
            or reference.get('extent_wsen') != [-180,-90,180,90]
            or reference.get('kind') != 'static reference night-lights composite, not contemporaneous with satellite clouds'):
        raise ValueError('Night lights must have explicit static-reference provenance and global grid')
    stem = source.stem + '_night_visual'
    target = out_dir / (stem + '.png')
    surface = out_dir / (stem + '_surface.png')
    coverage_path = out_dir / (stem + '_coverage.png')
    inputs = {source.resolve(), source.with_suffix('.json').resolve(),
              lights.resolve(), lights.with_suffix('.json').resolve()}
    if any(p.resolve() in inputs for p in [target,target.with_suffix('.json'),surface,
                                          surface.with_suffix('.json'),coverage_path]):
        raise ValueError('Night display outputs must not overwrite inputs')
    with Image.open(source) as image:
        if image.mode != 'RGBA' or image.size != (meta['width'],meta['height']) or image.width != 2*image.height:
            raise ValueError('IR must match its 2:1 RGBA global grid')
        data = np.asarray(image)
    if not np.isin(data[...,3],[0,255]).all() or not (data[...,0] == data[...,1]).all() or not (data[...,1] == data[...,2]).all():
        raise ValueError('IR must have grayscale RGB and binary genuine coverage')
    coverage = data[...,3] == 255
    # The 8-bit diagnostic quantizes reconstructed display temperatures to ~0.57 K.
    kelvin = 318.15 - data[...,0].astype(np.float32) * (145 / 255)
    clouds = night_cloud_rgba(kelvin, coverage)
    stamp = meta.get('reference_utc') or meta['observed_utc']
    weights = global_solar_weights(utc_time(stamp), meta['width'])
    # NASA's verified 13500x6750 reference exceeds Pillow's warning threshold.
    # Do not disable the hard pixel limit or allow arbitrary larger assets.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', Image.DecompressionBombWarning)
        with Image.open(lights) as image:
            if image.size != (reference['width'],reference['height']) or image.width != 2*image.height:
                raise ValueError('Reference dimensions differ from provenance')
            light_rgb = np.asarray(image.convert('RGB').resize((meta['width'],meta['height']),Image.Resampling.LANCZOS))
    displayed = np.rint(light_rgb.astype(np.float32) * weights.city_lights[...,None]).astype(np.uint8)
    displayed = np.maximum(displayed,np.array([4,5,12],dtype=np.uint8))
    # Missing IR is distinct from warm/clear-looking observations, not hidden.
    displayed[~coverage] = (24,11,35)
    out_dir.mkdir(parents=True,exist_ok=True)
    Image.fromarray(clouds).save(target)
    Image.fromarray(displayed).save(surface)
    Image.fromarray(coverage.astype(np.uint8)*255).save(coverage_path)
    visual = {**meta,'product':'ir-night-display','display_recipe':'ir-night-visual-v1',
              'display_mapping':None,
              'source_ir_image':str(source.resolve()), 'source_provenance':meta,
              'source_ir_coverage':coverage_path.name,'night_surface':surface.name,
              'is_cloud_mask':False,'is_opacity_retrieval':False,
              'opacity_display_curve':{'warm_k':293.15,'cold_k':193.15,'gamma':1.3},
              'temperature_quantization_k':145/255,
              'notes':'Artistic opacity from one IR band; cold surface may appear as cloud, '
                      'warm low cloud may fade. Not measured cloud fraction or optical thickness. '
                      'Coverage is separate from display opacity; no missing observations filled.'}
    target.with_suffix('.json').write_text(json.dumps(visual,indent=2),encoding='utf-8')
    surface.with_suffix('.json').write_text(json.dumps({
        'kind':'static night reference with computed solar gating and missing-IR tint',
        'source_reference':reference,'source_image':str(lights.resolve()),
        'model_utc':stamp,'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],
        'width':meta['width'],'height':meta['height'],
        'city_lights_transition_elevation_deg':[-6,0],
        'missing_ir_tint_srgb':[24,11,35], 'background_floor_srgb':[4,5,12],
        'is_contemporaneous_observation':False,
    },indent=2),encoding='utf-8')
    return target
