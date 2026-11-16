"""Bounded NASA 2016 500m static night reference, separate from 2022 weather."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
URL = ('https://assets.science.nasa.gov/content/dam/science/esd/eo/images/'
       'imagerecords/144000/144898/BlackMarble_2016_D1_geo.tif')
DOC = 'https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/'
HARD_LIMIT = 500_000_000
EXTENT = (96., 12., 154., 58.)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.raw.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.raw / 'BlackMarble_2016_D1_geo.tif'
    if not target.exists():
        head = requests.head(URL, headers={'Accept-Encoding': 'identity'}, timeout=20)
        head.raise_for_status()
        size = int(head.headers['Content-Length'])
        if not 0 < size <= HARD_LIMIT:
            raise ValueError('Source exceeds preflight budget')
        plan = dict(url=URL, documentation=DOC, expected_bytes=size, hard_limit=HARD_LIMIT,
                    etag=head.headers.get('ETag'), reference_year=2016,
                    scope='One 500m D1 tile only, no global download or weather acquisition')
        (args.raw / 'download_plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
        part = target.with_suffix('.tif.part')
        total = 0
        began = time.monotonic()
        headers = {'Accept-Encoding': 'identity', 'If-Match': head.headers['ETag']}
        with requests.get(URL, headers=headers, stream=True, timeout=(20, 30)) as response:
            response.raise_for_status()
            if int(response.headers.get('Content-Length', -1)) != size:
                raise ValueError('Body size differs from budget')
            with part.open('xb') as f:
                for chunk in response.iter_content(1024 * 1024):
                    total += len(chunk)
                    if total > size or total > HARD_LIMIT or time.monotonic() - began > 600:
                        raise ValueError('Download hard limit reached; partial retained')
                    f.write(chunk)
                    if total % (32 * 1024 * 1024) == 0:
                        print('DOWNLOADED', total, '/', size, flush=True)
        if total != size:
            raise ValueError('Incomplete body retained as .part')
        part.rename(target)
        plan.update(actual_bytes=total, sha256=sha(target), response_etag=response.headers.get('ETag'))
        (args.raw / 'download_verified.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    with rasterio.open(target) as src:
        if src.crs.to_epsg() != 4326 or src.width != 21600 or src.height != 21600:
            raise ValueError('Unexpected NASA tile grid')
        if not np.allclose(tuple(src.bounds), [90, 0, 180, 90], atol=1e-7):
            raise ValueError('D1 georeferencing differs')
        if src.count != 3 or src.dtypes != ('uint8',) * 3:
            raise ValueError('Expected 3-band display RGB, not calibrated radiance')
        win = from_bounds(*EXTENT, transform=src.transform).round_offsets().round_lengths()
        pixels = np.ascontiguousarray(src.read(window=win).transpose(1, 2, 0))
        extent = tuple(map(float, rasterio.windows.bounds(win, src.transform)))
        meta = dict(kind='static 2016 500m NASA display RGB, not 2022 contemporaneous radiance',
                    source_url=URL, documentation=DOC, raw_sha256=sha(target),
                    source_shape_yx=[src.height, src.width], source_crs=str(src.crs),
                    pixel_degrees=list(src.res), extent_wsen=extent,
                    native_window=[win.col_off, win.row_off, win.width, win.height],
                    output_shape=list(pixels.shape), resampling='none: integer native window',
                    reference_year=2016, credit='NASA Earth Observatory / Suomi NPP VIIRS')
    dest = args.out / 'east_asia_2016_500m.npy'
    with dest.open('xb') as f:
        np.save(f, pixels, allow_pickle=False)
    meta['output_sha256'] = sha(dest)
    (args.out / 'east_asia_2016_500m.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print('NATIVE WINDOW READY', pixels.shape, extent, flush=True)


if __name__ == '__main__':
    main()
