"""Bounded H09 review inputs; reuse the approved RGB and night transfers unchanged."""
import argparse
import gc
import json
from datetime import timedelta
from pathlib import Path

import h5py
import numpy as np
from pyproj import Transformer
from satpy import Scene

from ges.catalog import list_objects, s3_client, utc_time
from ges.download import read_manifest
from ges.goni_data import decode
from ges.goni_lowcloud import low_liquid_confidence, spectral_night_material
from ges.observed_rgb import _sha, rebuild_ahi_rgb
from ges.range_archive import RangeArchive
from ges.render import observation_interval
from ges.solar import solar_weights
from ges.storage import load_config

TIMES = {'0300': (134.9, 16.2), '0830': (133.8, 16.7), '1920': (131.4, 17.4)}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def identity_navigation(source, target):
    """Verify that explicit nearest registration preserves EVERY native IR sample."""
    if source.shape != target.shape or source.crs != target.crs:
        raise ValueError('Identity registration needs equal projection and dimensions')
    for count, start, step, original_start, original_step in [
        (target.width, target.area_extent[0], target.pixel_size_x, source.area_extent[0], source.pixel_size_x),
        (target.height, -target.area_extent[3], target.pixel_size_y, -source.area_extent[3], source.pixel_size_y)]:
        centres = start+(np.arange(count)+.5)*step
        indices = np.floor((centres-original_start)/original_step).astype(int)
        if not np.array_equal(indices, np.arange(count)):
            raise ValueError('IR nearest registration would change cell indices')
    return dict(method='Explicit nearest registration; all row and column centre mappings verified identity',
                max_extent_difference_m=float(np.max(np.abs(np.array(source.area_extent)-target.area_extent))))


def ir_only_metadata(metadata, out):
    """Use the existing IR-coverage fallback; never fabricate nighttime VIS."""
    out.mkdir(exist_ok=True)
    path = out/'rgb.npy'
    if not path.exists():
        values = np.lib.format.open_memmap(path, mode='w+', dtype=np.float32,
                                          shape=(*metadata['output_shape_yx'], 3))
        values[:] = np.nan
        values.flush()
        del values
    observation = {**metadata, 'source_fade_applied': False,
                   'photometry_profile': 'IR-only approved coverage fallback; VIS not used in night cameras'}
    write_json(out/'metadata.json', dict(rgb_sha256=_sha(path), observation_metadata=observation))


def l2_fields(stamp, area, out):
    """Exact provider bytes, delivered quality/units and independently checked navigation."""
    cfg = load_config()
    cache = out/'l2_fields.npz'
    if cache.exists() and (out/'l2_audit.json').exists():
        with np.load(cache) as data:
            return {k: data[k] for k in data.files}
    client = s3_client()
    objects = list_objects(client, 'noaa-himawari9', stamp.strftime('AHI-L2-FLDK-Clouds/%Y/%m/%d/%H%M/'))
    wanted = {'CMSK': ['CloudMask', 'CloudMaskQualFlag', 'CloudProbability'],
              'CPHS': ['CloudPhase', 'CloudPhaseFlag'],
              'CHGT': ['CldTopHght', 'ZcError', 'CloudHgtQF']}
    caps = {'CMSK': 220_000_000, 'CPHS': 80_000_000, 'CHGT': 300_000_000}
    fields, records = {}, []
    for kind, names in wanted.items():
        matches = [o for o in objects if f'AHI-{kind}_' in o['Key']]
        if len(matches) != 1:
            raise ValueError('Exact H09 L2 product absent: '+kind)
        obj = matches[0]
        folder = cfg.raw_dir/'champi_20261020_l2_ranges'/stamp.strftime('%H%M')/kind
        with RangeArchive(client, 'noaa-himawari9', obj['Key'], obj['Size'], obj['ETag'],
                          folder, cfg, max_bytes=caps[kind], block_size=262144) as archive:
            with h5py.File(archive, 'r') as source:
                def attr(name):
                    v = source.attrs[name]
                    return v.decode() if isinstance(v, bytes) else str(v)
                if attr('satellite_name') != 'Himawari-9' or attr('instrument_name') != 'AHI':
                    raise ValueError('L2 platform mismatch')
                start, end = (utc_time(attr(k)) for k in ['time_coverage_start', 'time_coverage_end'])
                if not (stamp <= start < stamp+timedelta(minutes=1) and start <= end < stamp+timedelta(minutes=10)):
                    raise ValueError('L2 UTC mismatch')
                if int(np.asarray(source['granule_level_quality_flag'][()]).ravel()[0]) != 0:
                    raise ValueError('Degraded L2 granule')
                checks = []
                for row, col in [(1500, 1800), (2000, 2700), (3000, 3400)]:
                    lon, lat = area.get_lonlat(row, col)
                    delta = max(abs(float(source['Longitude'][row, col])-lon),
                                abs(float(source['Latitude'][row, col])-lat))
                    if delta > .002:
                        raise ValueError('L2/HSD navigation mismatch')
                    checks.append(delta)
                for name in names:
                    var = source[name]
                    if var.shape[:2] != area.shape:
                        raise ValueError('L2/HSD dimensions differ')
                    if name in ['CldTopHght', 'ZcError']:
                        units = var.attrs['units']
                        if isinstance(units, bytes): units = units.decode()
                        if units != 'Meter': raise ValueError('Height units not metres')
                    selection = np.s_[:, :, 0] if var.ndim == 3 else np.s_[:, :]
                    fields[name] = decode(var, selection, archive)
                    print('L2_FIELD', stamp.strftime('%H%M'), name, flush=True)
                records.append(dict(kind=kind, start_utc=start.isoformat(), end_utc=end.isoformat(),
                                    navigation_error_degrees=checks, archive=archive.audit()))
        print('L2_READY', stamp.strftime('%H%M'), kind, records[-1]['archive']['new_bytes_this_run'], flush=True)
    np.savez_compressed(cache, **fields)
    write_json(out/'l2_audit.json', records)
    return fields


def prepare(stamp_id, *, material_only=False):
    import dask
    cfg = load_config()
    stamp = utc_time(f'2026-10-20T{stamp_id[:2]}:{stamp_id[2:]}:00Z')
    root = cfg.processed_dir/'champi_20261020_review_v1'
    out = root/stamp_id
    out.mkdir(exist_ok=True)
    manifest = read_manifest(cfg.raw_dir/f'himawari9_20261020T{stamp_id}00Z/scene.json')
    files = manifest['local_files']
    hashes = {p: _sha(p) for p in files}
    with dask.config.set(num_workers=2):
        scene = Scene(reader='ahi_hsd', filenames=[p for p in files if any(f'_{b}_' in p for b in ['B07', 'B13'])])
        scene.load(['B07', 'B13'])
        area = scene['B13'].attrs['area']
        assert area.shape == (5500, 5500)
        if stamp_id == '1920':
            target = area
        else:
            # HSD 500m/1km/2km scale factors are rounded differently. Use the
            # 1km VIS extent: its maximum difference from red is only 0.067m.
            first = [p for p in files if '_B01_' in p and '_S0110.' in p]
            navigation = Scene(reader='ahi_hsd', filenames=first)
            navigation.load(['B01'])
            target = navigation['B01'].attrs['area'].copy(width=5500, height=5500)
        registration = identity_navigation(area, target)
        projection = area.crs.to_dict()
        projection['sweep'] = 'y'
        projection['b'] = projection['a']*(1-1/projection['rf']) if 'rf' in projection else projection['b']
        metadata = dict(nominal_utc=stamp.isoformat(), projection=projection,
                        output_shape_yx=[5500, 5500], area_extent_m=list(target.area_extent),
                        input_file_sha256=hashes)
        # Same native footprint, integer 2km aggregation; never nearest decimation.
        if not material_only and not (out/'full/metadata.json').exists():
            print('RGB_FULL_START', stamp_id, flush=True)
            if stamp_id == '1920': ir_only_metadata(metadata, out/'full')
            else: rebuild_ahi_rgb(metadata, cfg.raw_dir/'reference/satpy_geocolor_v060', out/'full')
        lon, lat = TIMES[stamp_id]
        x, y = Transformer.from_crs('EPSG:4326', area.crs, always_xy=True).transform(lon, lat)
        col = int(round((x-target.area_extent[0])/target.pixel_size_x))
        row = int(round((target.area_extent[3]-y)/target.pixel_size_y))
        row, col = min(max(row, 450), 5050), min(max(col, 450), 5050)
        roi = [row-450, row+450, col-450, col+450]
        sub = target[roi[0]:roi[1], roi[2]:roi[3]]
        detail = {**metadata, 'output_shape_yx': [1800, 1800], 'area_extent_m': list(sub.area_extent)}
        segments = range(roi[0]//550+1, (roi[1]-1)//550+2)
        detail['input_file_sha256'] = {p: h for p, h in hashes.items()
            if any(f'_S{s:02d}10.' in Path(p).name for s in segments)}
        if not material_only and not (out/'detail/metadata.json').exists():
            print('RGB_DETAIL_START', stamp_id, flush=True)
            if stamp_id == '1920': ir_only_metadata(detail, out/'detail')
            else: rebuild_ahi_rgb(detail, cfg.raw_dir/'reference/satpy_geocolor_v060', out/'detail')
        if (out/'preparation.json').exists():
            print('PREPARED_CACHE', stamp_id, flush=True)
            return
        l2 = l2_fields(stamp, area, out)
        thermal = {b: np.asarray(scene[b].compute(num_workers=2), np.float32) for b in ['B13', 'B07']}
        for b in thermal:
            if scene[b].attrs['units'] != 'K': raise ValueError('IR brightness temperature must be K')
        start, end = map(utc_time, observation_interval(scene['B13'].attrs))
        sw_start, sw_end = map(utc_time, observation_interval(scene['B07'].attrs))
        assert abs((start-sw_start).total_seconds()) <= 1 and abs((end-sw_end).total_seconds()) <= 1
        rgba = np.empty((5500, 5500, 4), np.uint8)
        # Existing native renderer heights only; no experimental relief shader or inferred cloud heights.
        for first in range(0, 5500, 250):
            sl = slice(first, min(first+250, 5500))
            values = {k: v[sl] for k, v in l2.items()}
            mask, q = values['CloudMask'], values['CloudMaskQualFlag']
            p = values['CloudProbability']
            good = np.isfinite(p)&(p >= 0)&(p <= 1)&(q == 0)&np.isin(mask, [0, 1, 2, 3])
            p = np.where(good, p, np.where((q == 0)&np.isin(mask, [2, 3]), 1., 0.)).astype(np.float32)
            low = low_liquid_confidence(mask, q, values['CloudPhase'], values['CloudPhaseFlag'],
                values['CldTopHght']/1000, values['ZcError']/1000, values['CloudHgtQF'])
            lo, la = area[sl, :].get_lonlats()
            on_disk = np.isfinite(lo)&np.isfinite(la)
            safe_lon, safe_lat = np.where(on_disk, lo, 0), np.where(on_disk, la, 0)
            eligible = on_disk&(solar_weights(start, safe_lon, safe_lat).elevation_deg <= -6)&(solar_weights(end, safe_lon, safe_lat).elevation_deg <= -6)
            rgb, alpha = spectral_night_material(thermal['B13'][sl], thermal['B07'][sl], p, low, eligible)
            rgba[sl] = np.rint(np.clip(np.dstack([rgb, alpha]), 0, 1)*255).astype(np.uint8)
        valid = np.isfinite(thermal['B13'])&(thermal['B13'] >= 100)&(thermal['B13'] <= 350)
        # IR coverage is separate from display cloud opacity; no L2/VIS gap filling.
        full_support = valid
        np.save(out/'full/ir_support.npy', full_support, allow_pickle=False)
        np.save(out/'night_rgba.npy', rgba, allow_pickle=False)
        h, err = l2['CldTopHght'], l2['ZcError']
        qualified = np.isin(l2['CloudMask'], [2, 3])&(l2['CloudMaskQualFlag'] == 0)&(l2['CloudHgtQF'] == 0)
        qualified &= np.isfinite(h)&(h > 0)&(h <= 20000)&np.isfinite(err)&(err >= 0)&(err <= 3000)
        heights = np.where(qualified, h/1000, np.nan).astype(np.float32)
        np.save(out/'heights_km.npy', heights, allow_pickle=False)
        r0, r1, c0, c1 = roi
        np.save(out/'detail/night_rgba.npy', rgba[r0:r1, c0:c1], allow_pickle=False)
        np.save(out/'detail/heights_km.npy', heights[r0:r1, c0:c1], allow_pickle=False)
        support = np.repeat(np.repeat(valid[r0:r1, c0:c1], 2, 0), 2, 1)
        np.save(out/'detail/ir_support.npy', support, allow_pickle=False)
        write_json(out/'preparation.json', dict(nominal_utc=stamp.isoformat(), native_crop_yx=roi,
            scan_interval_utc=[start.isoformat(), end.isoformat()], raw_sha256=hashes,
            ir_to_vis_navigation=registration,
            rgb_profile='IR-only approved coverage fallback' if stamp_id == '1920' else 'ahi-area-mean-unsharpened-single-fade-v2',
            night_transfer='ges.goni_lowcloud.spectral_night_material, unchanged; delivered L2 confidence',
            height_policy='Unchanged native display with qualified L2 heights; unknowns remain NaN; no experimental cloud-relief shader',
            source_resolution='Full-disk RGB preview 2km; detail RGB 1km from unsharpened 500m red + 1km colour/NIR; night IR native 2km',
            storm_aimpoint_lonlat=[lon, lat], track_source='https://agora.ex.nii.ac.jp/digital-typhoon/summary/wnp/l/202630.html.en'))
    del l2, thermal, rgba, scene, heights
    gc.collect()
    print('PREPARED', stamp_id, flush=True)


if __name__ == '__main__':
    import faulthandler
    faulthandler.enable()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stamp', choices=TIMES)
    parser.add_argument('--material-only', action='store_true', help='Prepare independent IR/L2 fields while RGB is already computing')
    args = parser.parse_args()
    prepare(args.stamp, material_only=args.material_only)
