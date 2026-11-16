"""Rebuild observed AHI apparent RGB before destructive twilight display clipping.

This is an image-appearance correction, not a water reflectance retrieval.
No longitude/latitude-specific gain, generated sea colour or missing-data fill.
"""
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from .catalog import utc_time

PROFILE = 'ahi-area-mean-unsharpened-single-fade-v2'
PRODUCT = 'observed_twilight_rgb'
# Pyspectral's documented high-zenith reduction. One final 0..6deg display
# handoff is applied by ObservedDayRenderer; no SunZenithReducer in this RGB.
RECIPE = '''sensor_name: visir/ahi
modifiers:
  observed_rayleigh:
    modifier: !!python/name:satpy.modifiers.PSPRayleighReflectance
    atmosphere: us-standard
    aerosol_type: rayleigh_only
    reduce_lim_low: 70
    reduce_lim_high: 90
    reduce_strength: 1.0
    prerequisites:
    - name: B03
      modifiers: [sunz_corrected]
    optional_prerequisites:
    - satellite_azimuth_angle
    - satellite_zenith_angle
    - solar_azimuth_angle
    - solar_zenith_angle
composites:
  observed_ndvi_green:
    compositor: !!python/name:satpy.composites.spectral.NDVIHybridGreen
    limits: [0.15, 0.05]
    strength: 3.0
    prerequisites:
    - name: B02
      modifiers: [sunz_corrected, observed_rayleigh]
    - name: B03
      modifiers: [sunz_corrected, observed_rayleigh]
    - name: B04
      modifiers: [sunz_corrected]
    standard_name: toa_bidirectional_reflectance
  observed_twilight_rgb:
    compositor: !!python/name:satpy.composites.core.GenericCompositor
    prerequisites:
    - name: B03
      modifiers: [sunz_corrected, observed_rayleigh]
    - name: observed_ndvi_green
    - name: B01
      modifiers: [sunz_corrected, observed_rayleigh]
    standard_name: true_color
'''


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _native_crop(scene, target):
    """Aligned native footprints only; average samples without filling holes.

    Work on the requested raw footprint before angle corrections/compositing.
    Reject fractional grids rather than silently selecting nearby pixels.
    """
    import dask.array as da

    cropped = scene.copy()
    support = None
    for name in ['B01', 'B02', 'B03', 'B04']:
        dataset = scene[name]
        area = dataset.attrs['area']
        if area.crs != target.crs:
            raise ValueError('Native RGB requires the same source projection')
        extent = target.area_extent
        fx = target.pixel_size_x/area.pixel_size_x
        fy = target.pixel_size_y/area.pixel_size_y
        ix, iy = round(fx), round(fy)
        x = (extent[0]-area.area_extent[0])/area.pixel_size_x
        y = (area.area_extent[3]-extent[3])/area.pixel_size_y
        x0, y0 = round(x), round(y)
        # Archived navigation has sub-decimetre rounding differences. Validate
        # the final four extent edges in metres below, not just pixel fractions.
        if min(ix, iy) < 1 or not np.allclose([fx, fy], [ix, iy], rtol=0, atol=1e-5) or not np.allclose([x,y], [x0,y0], rtol=0, atol=1e-3):
            raise ValueError(f'Native RGB requires integer aligned footprint aggregation: {name} factors/offsets={fx,fy,x,y}')
        nx, ny = target.width*ix, target.height*iy
        if x0 < 0 or y0 < 0 or x0+nx > area.width or y0+ny > area.height:
            raise ValueError('Requested RGB footprint lies outside supplied raw segment grid')
        subarea = area[y0:y0+ny, x0:x0+nx]
        if not np.allclose(subarea.area_extent, extent, rtol=0, atol=.1):
            raise ValueError('Native RGB crop navigation mismatch')
        part = dataset.isel(y=slice(y0, y0+ny), x=slice(x0, x0+nx))
        part.attrs = {**dataset.attrs, 'area': subarea}
        cropped[name] = part
        valid = da.coarsen(np.all, da.isfinite(part.data), {0: iy, 1: ix}, trim_excess=False)
        support = valid if support is None else support & valid
    return cropped, support


def rebuild_ahi_rgb(metadata, auxiliary_dir, out, *, legacy=False):
    """Native projected area from metadata, offline HSD, isolated Satpy recipe.

    All source bands must have the requested explicit nominal UTC. Missing
    segments remain NaN. Existing scientific caches/configuration aren't edited.
    Cache reuse verifies recipe, source hashes and output payload hashes.
    """
    import dask
    import satpy
    from satpy import Scene
    from pyresample.geometry import AreaDefinition
    from satpy.enhancements.enhancer import get_enhanced_image

    out = Path(out)
    stamp = utc_time(metadata['nominal_utc'])
    source_hashes = metadata['input_file_sha256']
    files = [Path(p) for p in source_hashes if any(f'_B{b:02}_' in Path(p).name for b in [1, 2, 3, 4])]
    platforms = {p.name.split('_')[1] for p in files}
    if len(platforms) != 1 or not platforms.issubset({'H08', 'H09'}):
        raise ValueError('One actual Himawari-8 or Himawari-9 acquisition required')
    platform = next(iter(platforms))
    prefix = f'HS_{platform}_{stamp:%Y%m%d_%H%M}_'
    if {int(p.name.split('_B')[1][:2]) for p in files} != {1, 2, 3, 4}:
        raise ValueError('AHI B01/B02/B03/B04 raw observations required, not enhanced/clipped RGB')
    if not all(p.name.startswith(prefix) for p in files):
        raise ValueError('Every HSD band must match the same platform and nominal UTC')
    for p in files:
        if _sha(p) != source_hashes[str(p)]:
            raise ValueError('Raw observation hash mismatch: '+p.name)
    projection = metadata['projection']
    if projection['proj'] != 'geos' or projection.get('sweep', 'y') != 'y':
        raise ValueError('AHI native sweep-y area required')
    shape = tuple(metadata['output_shape_yx'])
    if len(shape) != 2 or min(shape) <= 0:
        raise ValueError('Native area shape required')
    profile = 'legacy-satpy-double-fade-control' if legacy else PROFILE
    product = 'true_color_ndvi_green' if legacy else PRODUCT
    signature = dict(profile=profile, recipe_sha256=hashlib.sha256(RECIPE.encode()).hexdigest(),
                     nominal_utc=stamp.isoformat(), shape=list(shape),
                     extent_m=metadata['area_extent_m'], projection=projection,
                     inputs={str(p): source_hashes[str(p)] for p in files})
    manifest = out/'metadata.json'
    if manifest.exists():
        record = json.loads(manifest.read_text())
        if record.get('satpy_version') != satpy.__version__:
            raise ValueError('Satpy version differs from cached photometry; use a new cache directory')
        if record['signature'] != signature:
            raise ValueError('Existing RGB cache provenance differs; use a new output directory')
        if _sha(out/'rgb.npy') != record['rgb_sha256']:
            raise ValueError('RGB cache hash mismatch')
        return np.load(out/'rgb.npy', allow_pickle=False), record['observation_metadata']
    out.mkdir(parents=True, exist_ok=False)
    config = out/'satpy_config'
    (config/'composites').mkdir(parents=True)
    (config/'composites/ahi.yaml').write_text(RECIPE, encoding='utf-8')
    auxiliary_dir = Path(auxiliary_dir).resolve()
    # Pyspectral configuration is an existing offline auxiliary cache, not an edit.
    ps_config = auxiliary_dir.parent/'pyspectral/pyspectral.yaml'
    previous_env = os.environ.get('PSP_CONFIG_FILE')
    os.environ['PSP_CONFIG_FILE'] = str(ps_config)
    try:
        from pyspectral.rayleigh import Rayleigh
        corrector = Rayleigh(f'Himawari-{int(platform[1:])}', 'ahi', atmosphere='us-standard', aerosol_type='rayleigh_only')
        if corrector.do_download:
            raise ValueError('Offline Pyspectral cache required')
        paths = list(satpy.config.get('config_path')) + [str(config.resolve())]
        with satpy.config.set(config_path=paths, data_dir=str(auxiliary_dir), download_aux=False), dask.config.set(num_workers=2):
            scene = Scene(reader='ahi_hsd', filenames=[str(p.resolve()) for p in files])
            area = AreaDefinition('actual_observed_area', 'actual source area', 'geos', projection,
                                  shape[1], shape[0], metadata['area_extent_m'])
            if legacy:
                scene.load([product], generate=True, unload=False)
                result = scene.resample(area, resampler='nearest', radius_of_influence=5000, unload=False)
                support = None
            else:
                scene.load(['B01', 'B02', 'B03', 'B04'])
                scene, support = _native_crop(scene, area)
                scene.load([product], generate=True, unload=False)
                result = scene.resample(area, resampler='native', unload=False)
            print('RGB_DEPENDENCIES_READY', stamp.isoformat(), product, flush=True)
            dataset = result[product]
            display = get_enhanced_image(dataset).data.transpose('y', 'x', 'bands')
            if support is not None:
                # NativeResampler uses nanmean; do not let partial footprints
                # masquerade as complete observations at missing-data borders.
                display = display.where(support[..., None])
            rgb = np.asarray(display.compute(
                scheduler='threads', num_workers=2).data, np.float32)
            if rgb.shape != (*shape, 3):
                raise ValueError('Unexpected observed RGB dimensions')
            from .render import observation_interval
            interval = observation_interval(dataset.attrs)
    finally:
        if previous_env is None:
            os.environ.pop('PSP_CONFIG_FILE', None)
        else:
            os.environ['PSP_CONFIG_FILE'] = previous_env
    target = out/'rgb.npy'
    with target.open('xb') as stream:
        np.save(stream, rgb, allow_pickle=False)
    observation_meta = {**metadata, 'photometry_profile': profile, 'source_fade_applied': bool(legacy),
                        'source_product': product, 'scan_interval_from_composite': interval}
    record = dict(signature=signature, rgb_sha256=_sha(target), observation_metadata=observation_meta,
                  finite_fraction=float(np.isfinite(rgb).all(-1).mean()), satpy_version=satpy.__version__,
                  limits='Apparent RGB; zenith-angle reduction of Rayleigh subtraction, not a calibrated twilight atmosphere/water retrieval. '
                         'Native footprint means without ratio sharpening; any missing raw contributor invalidates output. '
                         'No interpolated weather or generated structure. '
                         'At high solar zenith the retained path appearance must not be added a second time in the renderer.')
    manifest.write_text(json.dumps(record, indent=2), encoding='utf-8')
    return rgb, observation_meta
