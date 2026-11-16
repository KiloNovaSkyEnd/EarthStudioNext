"""Build resumable, separate 11K lossless-PNG display sequences from sealed 22K."""
import argparse
import concurrent.futures
import gc
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
from PIL import Image
import rasterio
from rasterio.windows import Window

from ges_next.compact_weather import reduce_rgba2, source_vrt, read_reduced_tiles
from ges_next.isolation import ROOT, require_writable


SOURCE = ROOT / 'data/exports/H9_20261020_12h_Blender_v1'
TARGET = ROOT / 'data/exports/H9_20261020_12h_Blender_11K_v1'
Image.MAX_IMAGE_PIXELS = 130_000_000  # Only known11000x11000 derivatives in this bounded tool.


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    part = path.with_suffix(path.suffix + '.part')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    part.replace(path)


def prepare(index):
    began = time.perf_counter()
    source, target = SOURCE, TARGET
    node = read(source / 'sequence_manifest.json')['nodes'][index - 1]
    folder = target / 'assets/disk'
    path, receipt = folder / f'weather_{index:04d}.png', target / 'receipts' / f'{index:04d}.json'
    if receipt.exists():
        record = read(receipt)
        if path.stat().st_size != record['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Existing derivative changed')
        return record
    if path.exists():
        raise FileExistsError('Unreceipted derivative preserved')
    if shutil.disk_usage(target).free < 8 * 1024**3:
        raise RuntimeError('Compact conversion stopped at 8GiB free-space reserve')
    pixels = np.zeros((11000, 11000, 4), dtype=np.uint8)
    fingerprints = []
    if not node['missing']:
        master = read(source / 'native_master.json')
        entries = {entry['path']: entry for entry in read(source / 'sequence_manifest.json')['files']}
        for tile in master['tiles']:
            relative = f"assets/{Path(tile['path']).stem}/weather_{index:04d}.tif"
            file = source / relative
            stat = file.stat()
            if stat.st_size != entries[relative]['bytes']:
                raise ValueError('Native input size differs from sealed manifest')
            fingerprints.append((file, stat.st_size, stat.st_mtime_ns))
        qualification = target / 'tile_reduction_qualification.json'
        if qualification.exists() and read(qualification).get('all_three_full_frames_exact'):
            del pixels
            pixels = read_reduced_tiles(source, master, index)
        else:
            vrt = target / 'work' / f'{index:04d}.vrt'
            source_vrt(master, source, index, vrt)
            with rasterio.Env(GDAL_CACHEMAX=64 * 1024 * 1024), rasterio.open(vrt) as dataset:
                for row in range(0, 22000, 256):
                    rows = min(256, 22000 - row)
                    block = np.moveaxis(dataset.read(window=Window(0, row, 22000, rows)), 0, -1)
                    pixels[row // 2:(row + rows) // 2] = reduce_rgba2(block)
    reduction_seconds = time.perf_counter() - began
    part = path.with_suffix('.part.png')
    Image.fromarray(pixels).save(part, compress_level=1)
    encoded_seconds = time.perf_counter() - began - reduction_seconds
    with Image.open(part) as image:
        if image.size != (11000, 11000) or image.mode != 'RGBA' or not np.array_equal(np.asarray(image), pixels):
            raise ValueError('PNG differs from the explicitly reduced RGBA result')
    for file, size, modified in fingerprints:
        stat = file.stat()
        if (stat.st_size, stat.st_mtime_ns) != (size, modified):
            raise ValueError('Native source changed during conversion')
    record = dict(index=index, utc=node['utc'], missing=node['missing'], path=path.relative_to(target).as_posix(),
                  bytes=part.stat().st_size, sha256=hashlib.sha256(part.read_bytes()).hexdigest(),
                  reduction_seconds=reduction_seconds, encode_seconds=encoded_seconds,
                  seconds=time.perf_counter() - began, shape=[11000, 11000], png_rgba_roundtrip_exact=True,
                  spatial_reduction='alpha-weighted2x2 average of retained22K composite; not new1km unsharpened Satpy recomposition')
    part.replace(path)
    write(receipt, record)
    del pixels
    gc.collect()
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--workers', type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    target = require_writable(TARGET)
    target.mkdir(exist_ok=True)
    for name in ['assets/disk', 'receipts', 'work']:
        (target / name).mkdir(parents=True, exist_ok=True)
    source = read(SOURCE / 'sequence_manifest.json')
    indices = [1, 37, 73] if args.pilot else list(range(1, 74))
    started = time.perf_counter()
    workers = args.workers
    if workers > 1:
        import psutil
        if psutil.virtual_memory().available < 9 * 1024**3:
            workers = 1
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(prepare, index): index for index in indices}
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            print('COMPACT_FRAME', json.dumps(row), flush=True)
    receipts = [read(path) for path in sorted((target / 'receipts').glob('*.json'))]
    status = dict(mode='pilot' if args.pilot else 'full', prepared=len(receipts), expected=73,
                  bytes=sum(row['bytes'] for row in receipts), elapsed_seconds=time.perf_counter() - started,
                  workers=workers, source_22k_retained=True, conversion='22K composite ->11K area average ->lossless RGBA PNG')
    write(target / 'preparation_status.json', status)
    if len(receipts) == 73:
        manifest = dict(source)
        manifest['schema'] = 'earthstudio.compact_weather_sequence.v1'
        manifest['native_shape'] = [11000, 11000]
        manifest['source_native_shape'] = [22000, 22000]
        manifest['tiles'] = 1
        manifest['files'] = [dict(path=row['path'], bytes=row['bytes'], sha256=row['sha256'], missing=row['missing']) for row in receipts]
        manifest['storage'] = 'Explicit11K area-reduced display derivative; lossless PNG encoding, retained22K source separate'
        manifest['raw_L1_required'] = False
        write(target / 'sequence_manifest.json', manifest)
    print('COMPACT_STATUS', json.dumps(status), flush=True)


if __name__ == '__main__':
    main()
