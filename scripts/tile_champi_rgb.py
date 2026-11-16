"""Checkpointed execution of the unchanged pointwise approved RGB recipe."""
import argparse
import bz2
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from ges.download import read_manifest
from ges.observed_rgb import PROFILE, _sha, rebuild_ahi_rgb
from ges.storage import load_config, preflight
from scripts.prepare_champi_review import write_json


def decode_inputs(stamp):
    cfg = load_config()
    root = cfg.processed_dir/'champi_20261020_review_v1'/stamp
    out = root/'decoded_hsd'
    out.mkdir(exist_ok=True)
    manifest = out/'provenance.json'
    if manifest.exists():
        records = json.loads(manifest.read_text())
        if all(Path(r['decoded']).exists() for r in records):
            if all(Path(r['decoded']).stat().st_size == r['decoded_bytes'] and _sha(r['decoded']) == r['decoded_sha256'] for r in records):
                return records
            raise ValueError('Decoded scratch identity changed')
        # Regenerate reproducible scratch after deliberate cleanup; raw is authoritative.
        if any(_sha(r['raw']) != r['raw_sha256'] for r in records):
            raise ValueError('Original raw identity changed')
    raw = read_manifest(cfg.raw_dir/f'himawari9_20261020T{stamp}00Z/scene.json')
    files = [Path(p) for p in raw['local_files'] if any(f'_B{b:02d}_' in p for b in [1, 2, 3, 4])]
    preflight(2_000_000_000, out, cfg)
    def decode_one(source):
        target = out/source.with_suffix('').name
        partial = target.with_suffix('.DAT.part')
        digest = hashlib.sha256()
        # Reading to EOF verifies the original bzip2 CRC. No calibration or sample changes.
        with bz2.open(source, 'rb') as src, partial.open('wb') as dst:
            while chunk := src.read(4*1024*1024):
                digest.update(chunk)
                dst.write(chunk)
        os.replace(partial, target)
        return dict(raw=str(source.resolve()), raw_sha256=_sha(source), decoded=str(target.resolve()),
                    decoded_sha256=digest.hexdigest(), decoded_bytes=target.stat().st_size,
                    operation='Lossless bzip2 decode with CRC; original raw retained')
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(decode_one, files))
    write_json(manifest, records)
    print('DECODED', stamp, sum(r['decoded_bytes'] for r in records), flush=True)
    return records


def grid_metadata(stamp, records):
    from satpy import Scene
    first = [r['decoded'] for r in records if '_B01_' in r['decoded'] and '_S0110.' in r['decoded']]
    scene = Scene(reader='ahi_hsd', filenames=first)
    scene.load(['B01'])
    area = scene['B01'].attrs['area'].copy(width=5500, height=5500)
    pr = area.crs.to_dict()
    pr['sweep'] = 'y'
    pr['b'] = pr['a']*(1-1/pr['rf'])
    meta = dict(nominal_utc=f'2026-10-20T{stamp[:2]}:{stamp[2:]}:00+00:00', projection=pr,
                output_shape_yx=[5500, 5500], area_extent_m=list(area.area_extent),
                input_file_sha256={r['decoded']: r['decoded_sha256'] for r in records})
    return area, meta


def region_metadata(area, meta, r0, r1, c0, c1):
    sub = area[r0:r1, c0:c1]
    # Keep ALL source headers as in a monolithic scene, including orbital
    # metadata aggregation. Crop only the computational footprint, never inputs.
    return {**meta, 'output_shape_yx': [r1-r0, c1-c0], 'area_extent_m': list(sub.area_extent)}


def tile_worker(job):
    metadata, destination, auxiliary = job
    rgb, _ = rebuild_ahi_rgb(metadata, auxiliary, destination)
    return str(destination), list(rgb.shape)


def run(stamp):
    cfg = load_config()
    root = cfg.processed_dir/'champi_20261020_review_v1'/stamp
    cached = root/'full/metadata.json'
    if cached.exists():
        record = json.loads(cached.read_text())
        if _sha(root/'full/rgb.npy') != record['rgb_sha256']:
            raise ValueError('Full RGB cache hash mismatch')
        print('FULL_RGB_CACHE', stamp, flush=True)
        return
    records = decode_inputs(stamp)
    area, meta = grid_metadata(stamp, records)
    auxiliary = cfg.raw_dir/'reference/satpy_geocolor_v060'
    tasks = []
    for r0 in range(0, 5500, 1375):
        for c0 in range(0, 5500, 1375):
            dest = root/'rgb_tiles_all_segments'/f'{r0:04d}_{c0:04d}'
            tasks.append((region_metadata(area, meta, r0, r0+1375, c0, c0+1375), dest, auxiliary))
    # Each cache is independent and restartable. Bounded footprints avoid full-disk PROJ allocations.
    with ProcessPoolExecutor(max_workers=2) as pool:
        for result in as_completed([pool.submit(tile_worker, t) for t in tasks]):
            print('TILE_READY', stamp, *result.result(), flush=True)
    full = root/'full'
    full.mkdir(exist_ok=True)
    values = np.lib.format.open_memmap(full/'rgb.npy', mode='w+', dtype=np.float32, shape=(5500, 5500, 3))
    for metadata, dest, _ in tasks:
        row, col = map(int, dest.name.split('_'))
        record = json.loads((dest/'metadata.json').read_text())
        if _sha(dest/'rgb.npy') != record['rgb_sha256']: raise ValueError('Tile payload changed')
        values[row:row+1375, col:col+1375] = np.load(dest/'rgb.npy', mmap_mode='r')
    values.flush()
    # A separate native crop crosses a four-tile junction. Test the actual recipe,
    # not a PNG blur or blending feather. The entire recipe is pointwise after native means.
    probe_meta = region_metadata(area, meta, 1343, 1407, 1343, 1407)
    probe, _ = rebuild_ahi_rgb(probe_meta, auxiliary, root/'tile_seam_probe')
    got = np.asarray(values[1343:1407, 1343:1407])
    support_equal = np.array_equal(np.isfinite(got), np.isfinite(probe))
    delta = float(np.nanmax(np.abs(got-probe)))
    if not support_equal or delta > 2e-5:
        raise ValueError(f'Tiled recipe differs from independent native crop: {support_equal}, {delta}')
    del values
    obs = {**meta, 'source_fade_applied': False, 'photometry_profile': PROFILE,
           'execution': '16 aligned native crops, unchanged recipe; no seam blending',
           'original_raw_provenance': str((root/'decoded_hsd/provenance.json').resolve())}
    write_json(full/'metadata.json', dict(observation_metadata=obs, rgb_sha256=_sha(full/'rgb.npy'),
        tiled_execution=True, seam_probe_support_equal=support_equal, seam_probe_max_abs_float=delta,
        tiles=[str(t[1].resolve()) for t in tasks]))
    print('FULL_RGB_READY', stamp, 'seam_max_abs', delta, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stamp', choices=['0300', '0830'])
    run(parser.parse_args().stamp)
