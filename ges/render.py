"""Geographic equirectangular products from measured satellite pixels. No inferred cloud pixels."""
from pathlib import Path
from datetime import timezone
import json
import numpy as np
from PIL import Image
from .download import read_manifest
from .catalog import utc_time

BINS = np.array([-100,-90,-80,-70,-60,-50,-40,-30,-20,-10,0,10,20,30,50], dtype=np.float32)
# Experimental grey IR-BD approximation only, NOT a standard agency calibration LUT.
PALETTE = np.array([(15,15,15),(55,55,55),(110,110,110),(195,195,195),
                    (245,245,245),(255,255,255),(25,25,25),(80,80,80),
                    (125,125,125),(185,185,185),(218,218,218),
                    (235,235,235),(140,140,140),(50,50,50)], dtype=np.uint8)

IR_GRAY_RECIPE = 'ir-gray-cold-white-v2'


def ir_to_rgba(data: np.ndarray, units: str, mode: str='bd') -> Image.Image:
    if units.lower() not in ('k','kelvin'):
        raise ValueError(f'无法确认 IR 波段亮温单位为 K，实际为：{units!r}。停止处理，以免错误制图。')
    valid = np.isfinite(data) & (data >= 100) & (data <= 350)
    celsius = data.astype(np.float32)-273.15
    if mode == 'bd':
        index = np.clip(np.searchsorted(BINS, np.where(valid, celsius, -1000), side='right')-1,0,len(PALETTE)-1)
        rgb = PALETTE[index]
    elif mode == 'gray':
        # Missing/out-of-range observations stay transparent; don't cast NaN to uint8.
        display_celsius = np.where(valid, celsius, 45)
        val = np.uint8(np.rint(np.clip((45 - display_celsius) / 145 * 255, 0, 255)))
        rgb = np.repeat(val[...,None],3,axis=2)
    else:
        raise ValueError('mode should be bd or gray')
    rgba = np.dstack((rgb, np.where(valid,255,0).astype(np.uint8)))
    return Image.fromarray(rgba, 'RGBA')


def make_global_area(width: int):
    from pyresample import create_area_def
    if not (512 <= width <= 8192) or width % 2:
        raise ValueError('输出宽度必须是 512~8192 的偶数')
    return create_area_def('global_lonlat', {'proj':'longlat','datum':'WGS84'},
                           area_extent=(-180.0,-90.0,180.0,90.0),
                           shape=(width//2,width), units='degrees')


def create_satpy_scene(files: list[str], satellite: str):
    from satpy import Scene
    if satellite.startswith('himawari'):
        reader='ahi_hsd'
    elif satellite.startswith('goes'):
        reader='abi_l2_nc'
    elif satellite.startswith('meteosat_'):
        reader='seviri_l1b_native'
    else:
        raise ValueError('Unverified satellite/reader mapping')
    return Scene(reader=reader, filenames=files)


def mask_goes_ir_quality(scene, files: list[str], band: str) -> str:
    """MCMIP has per-band DQF; Satpy's generic DQF filter doesn't apply it."""
    import netCDF4
    if len(files) != 1:
        raise ValueError('GOES MCMIP IR expects exactly one scene file')
    with netCDF4.Dataset(files[0]) as source:
        quality = source[f'DQF_{band}']
        meanings = quality.flag_meanings.split()
        good_value = int(quality.flag_values[meanings.index('good_pixel_qf')])
        good = np.ma.filled(quality[:], 255) == good_value
    data = scene[band]
    if good.shape != data.shape:
        raise ValueError('GOES quality mask shape differs from the IR dataset')
    scene[band] = data.where(good)
    return f'DQF_{band} == {good_value} (good_pixel_qf only)'


def _reader_utc(value):
    if value is None:
        return None
    # Satpy reader timestamps are documented UTC even when naive.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def observation_interval(attrs):
    """SEVIRI exposes nominal 15-min slots separately from actual scan times."""
    times=attrs.get('time_parameters',{})
    return (_reader_utc(times.get('observation_start_time',attrs.get('start_time'))),
            _reader_utc(times.get('observation_end_time',attrs.get('end_time'))))


def render(manifest: Path, out_dir: Path, product: str, width: int=2048) -> Path:
    meta = read_manifest(manifest)
    satellite = meta['satellite']
    product = product.lower()
    if product not in ('rgb','ir-bd','ir-gray'):
        raise ValueError('支持 rgb、ir-bd、ir-gray')
    area = make_global_area(width)
    scene = create_satpy_scene(meta['local_files'], satellite)
    if satellite.startswith('meteosat_') and product=='rgb':
        raise ValueError('SEVIRI RGB has not been verified; use ir-gray or ir-bd')
    ir_name = 'B13' if satellite.startswith('himawari') else 'IR_108' if satellite.startswith('meteosat_') else 'C13'
    dataset = 'true_color' if product=='rgb' else ir_name
    try:
        scene.load([dataset])
    except Exception as exc:
        raise RuntimeError(f'Satpy 无法读取 {dataset}；检查是否下载了完整波段及分段。原始错误：{exc}') from exc
    quality_policy = ('Satpy RGB writer coverage mask; no additional source quality filter'
                      if product == 'rgb' else
                      'finite IR values in 100..350 K; no additional source quality filter')
    if satellite.startswith('goes') and product != 'rgb':
        quality_policy = mask_goes_ir_quality(scene, meta['local_files'], ir_name)
    source_attrs = scene[dataset].attrs
    scan_start,scan_end=observation_interval(source_attrs)
    if satellite.startswith('meteosat_'):
        expected_platform={'MSG4':'Meteosat-11','MSG1':'Meteosat-8'}[meta['platform']]
        if (source_attrs.get('platform_name')!=expected_platform or
                source_attrs.get('units')!='K' or
                abs(source_attrs['wavelength'].central-10.8)>.01 or
                scan_start!=meta['scan_start_utc'] or scan_end!=meta['scan_end_utc']):
            raise ValueError('SEVIRI header/platform/band/timing differs from real catalog manifest')
        quality_policy='Satpy native count-zero masking and nominal radiometric calibration; finite 100..350 K; no extra scanline flag filter'
    # Global lon/lat bounds cross AHI's visible disk at the date line. Satpy's
    # rectangular source reduction can discard valid pixels east of +180.
    resampled = scene.resample(area, resampler='nearest', reduce_data=False)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f'{meta["scene_id"]}_{product}_{width}.png'
    out = out_dir / name
    if product=='rgb':
        resampled.save_dataset('true_color', filename=str(out), writer='simple_image')
        # Satpy geo-resampling should mark outside view with fill / alpha.
        # Reject images with no alpha: black outside disk must NOT be displayed as observed.
        with Image.open(out) as im:
            if 'A' not in im.getbands():
                out.unlink(missing_ok=True)
                raise RuntimeError('RGB 输出没有透明覆盖掩膜，拒绝将未观测区域显示为真实地球云层。')
    else:
        da = resampled[ir_name]
        units = da.attrs.get('units', '')
        values = da.compute().values
        ir_to_rgba(np.ma.filled(values,np.nan),str(units),'bd' if product=='ir-bd' else 'gray').save(out)
    sidecar = {'source_scene':str(manifest.resolve()),'source_satellite':satellite,
               'observed_utc':meta['observed_utc'],'product':product,
               'source_dataset':dataset, 'source_units':str(source_attrs.get('units', '')),
               'source_objects':meta.get('keys', []),
               'scan_start_utc':scan_start,
               'scan_end_utc':scan_end,
               'source_platform_name':source_attrs.get('platform_name'),
               'source_wavelength_um':float(source_attrs['wavelength'].central) if 'wavelength' in source_attrs else None,
               'nominal_start_utc':_reader_utc(source_attrs.get('start_time')),
               'nominal_end_utc':_reader_utc(source_attrs.get('end_time')),
               'quality_policy':quality_policy,
               'display_recipe':IR_GRAY_RECIPE if product == 'ir-gray' else product,
               'display_mapping':{'cold_white_c':-100,'warm_black_c':45}
                                 if product == 'ir-gray' else None,
               'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],
               'width':width,'height':width//2,
               'pixel_method':'nearest-neighbor','is_interpolated_time':False,
               'notes':'IR-BD is experimental display LUT, not official Dvorak product; RGB uses Satpy composite; check solar illumination.'}
    out.with_suffix('.json').write_text(json.dumps(sidecar,ensure_ascii=False,indent=2),encoding='utf-8')
    return out


def combine_images(images: list[Path], out: Path, reference_utc=None) -> Path:
    """Strict observed coverage overlay with UTC offsets and source-index map.

    First input wins. Only binary observed coverage masks on identical global
    grids/products are accepted; no radiometric blending or time interpolation.
    """
    if not images:
        raise ValueError('至少需要一个已经经纬度投影的卫星影像')
    if len(images) > 255:
        raise ValueError('Source-index PNG supports at most 255 sources')
    out = Path(out)
    if out.suffix.lower() != '.png':
        raise ValueError('Overlay output must be a PNG file')
    index_path = out.with_name(out.stem + '_source_index.png')
    outputs = {p.resolve() for p in (out, out.with_suffix('.json'), index_path)}
    if any(p.resolve() in outputs or p.with_suffix('.json').resolve() in outputs for p in images):
        raise ValueError('Overlay outputs must not overwrite source images or metadata')
    canvas = None
    source = []
    grid = None
    coverage = None
    if reference_utc is not None:
        reference_utc = utc_time(reference_utc.isoformat())
    for number, img in enumerate(images, 1):
        meta = json.loads(img.with_suffix('.json').read_text(encoding='utf-8'))
        observed = utc_time(meta['observed_utc'])
        if reference_utc is None:
            reference_utc = observed
        current_grid = (meta['projection'], meta['extent_wsen'], meta['width'], meta['height'], meta['product'],
                        meta.get('display_recipe'),meta.get('display_mapping'))
        if meta['product'] not in ('ir-gray','ir-bd','rgb'):
            raise ValueError('Coverage overlay requires observed products, not artistic display opacity')
        if current_grid[0] != 'EPSG:4326' or current_grid[1] != [-180, -90, 180, 90]:
            raise ValueError('Overlay requires the standard global EPSG:4326 grid')
        if grid is not None and current_grid != grid:
            raise ValueError('Overlay source grids, products or display recipes differ')
        grid = current_grid
        with Image.open(img) as im:
            if im.mode != 'RGBA' or im.size != (meta['width'], meta['height']) or im.width != 2 * im.height:
                raise ValueError('Overlay requires 2:1 RGBA matching its provenance dimensions')
            pixels = np.asarray(im)
            alpha = pixels[..., 3]
            if not np.isin(alpha, [0, 255]).all():
                raise ValueError('Overlay requires binary observed coverage alpha (0/255)')
            observed_mask = alpha == 255
            if canvas is None:
                canvas = np.zeros_like(pixels)
                coverage = np.zeros(alpha.shape, dtype=np.uint8)
            new = observed_mask & (coverage == 0)
            overlap = observed_mask & (coverage != 0)
            canvas[new] = pixels[new]
            coverage[new] = number
        source.append({'index':number, 'image':str(img.resolve()),
                       'source_satellite':meta['source_satellite'],
                       'observed_utc':observed.isoformat().replace('+00:00', 'Z'),
                       'offset_seconds':(observed - reference_utc).total_seconds(),
                       'observed_pixels':int(observed_mask.sum()),
                       'contributed_pixels':int(new.sum()),
                       'overlap_pixels':int(overlap.sum()), 'provenance':meta})
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(canvas).save(out)
    Image.fromarray(coverage).save(index_path)
    out.with_suffix('.json').write_text(json.dumps({
        'sources':source, 'method':'ordered coverage overlay (NOT seamless satellite fusion)',
        'reference_utc':reference_utc.isoformat().replace('+00:00', 'Z'),
        'max_source_time_span_seconds':max(s['offset_seconds'] for s in source) - min(s['offset_seconds'] for s in source),
        'projection':grid[0], 'extent_wsen':grid[1], 'width':grid[2], 'height':grid[3], 'product':grid[4],
        'display_recipe':grid[5], 'display_mapping':grid[6],
        'source_index_map':index_path.name, 'source_index_zero':'no observation',
        'observed_pixels':int(np.count_nonzero(coverage)),
        'missing_pixels':int(np.count_nonzero(coverage == 0)),
        'is_interpolated_time':False,
        'disclaimer':'Different scan times and sensor spectral responses are retained. '
                     'No radiometric seam correction, temporal interpolation or gap filling.',
    },ensure_ascii=False,indent=2),encoding='utf-8')
    return out
