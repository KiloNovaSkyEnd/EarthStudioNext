"""Independent NOAA HSD -> unmodified Satpy geo_color -> PNG. No ges imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def acquire():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED, max_pool_connections=8))
    day = datetime.now(timezone.utc).strftime('%Y/%m/%d')
    prefixes = s3.list_objects_v2(Bucket='noaa-himawari9', Prefix=f'AHI-L1b-FLDK/{day}/', Delimiter='/')['CommonPrefixes']
    bands = ('B01', 'B02', 'B03', 'B04', 'B07', 'B13')
    for pref in reversed(prefixes):
        objects = s3.list_objects_v2(Bucket='noaa-himawari9', Prefix=pref['Prefix']).get('Contents', [])
        objects = [o for o in objects if any(f'_{b}_' in o['Key'] for b in bands)]
        if len(objects) == 60:
            break
    else:
        raise RuntimeError('No complete current-day scan')
    size = sum(o['Size'] for o in objects)
    assert size < 3_000_000_000
    assert shutil.disk_usage(ROOT).free > size + 15_000_000_000
    scan = Path(objects[0]['Key']).name.split('_')
    raw = ROOT/'data/raw'/f'satpy_direct_h09_{scan[2]}T{scan[3]}Z'
    raw.mkdir(exist_ok=True)
    print('ACQUIRE', pref['Prefix'], 'bytes', size, flush=True)

    def get(o):
        path = raw/Path(o['Key']).name
        if not path.exists() or path.stat().st_size != o['Size']:
            tmp = path.with_suffix(path.suffix+'.part')
            s3.download_file('noaa-himawari9', o['Key'], str(tmp))
            assert tmp.stat().st_size == o['Size']
            tmp.replace(path)
        return dict(key=o['Key'], size=o['Size'], etag=o['ETag'], sha256=hashlib.file_digest(path.open('rb'), 'sha256').hexdigest())
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(get, objects))
    metadata = dict(bucket='noaa-himawari9', prefix=pref['Prefix'], acquired_utc=datetime.now(timezone.utc).isoformat(), files=records)
    (raw/'source.json').write_text(json.dumps(metadata, indent=2))
    print('RAW_READY', raw, flush=True)
    return raw


def render(raw, view):
    if view == 'regional':
        return regional_from_disk(raw)
    ref = ROOT/'data/raw/reference'
    os.environ['PSP_CONFIG_FILE'] = str(ref/'pyspectral/pyspectral.yaml')
    os.environ['OMP_NUM_THREADS'] = '2'
    os.environ['PYTROLL_CHUNK_SIZE'] = '2048'
    import dask
    import logging
    logging.basicConfig(level=logging.INFO)
    import satpy
    from satpy import Scene
    from pyresample.geometry import AreaDefinition
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    satpy.config.set(data_dir=str(ref/'satpy_geocolor_v060'))
    dask.config.set(scheduler='threads', num_workers=2, **{'array.chunk-size': '64MiB'})
    files = sorted(str(p) for p in raw.glob('*.bz2')) or sorted(str(p) for p in raw.glob('*.DAT'))
    scene = Scene(reader='ahi_hsd', filenames=files)
    print('LOAD', view, satpy.__version__, flush=True)
    if view == 'front':
        scene.load(['geo_color'])
        target = AreaDefinition('champi_front', 'Champi orthographic front', 'ortho',
            {'proj': 'ortho', 'lon_0': 130.7, 'lat_0': 18.0, 'datum': 'WGS84', 'units': 'm'},
            4096, 4096, (-1024000, -1024000, 1024000, 1024000))
        print('RESAMPLE', target.shape, flush=True)
        res = scene.resample(target, resampler='nearest', radius_of_influence=6000)
    else:
        bands = ['B01', 'B02', 'B03', 'B04', 'B07', 'B13']
        scene.load(bands)
        target = scene['B03'].attrs['area'].copy(width=11000, height=11000)
        # Native aggregation/repetition for aligned HSD bands avoids an enormous
        # and unnecessary full-disk KD tree. Only the georeferenced static
        # ancillary maps require geographic nearest-neighbour reprojection.
        print('NATIVE_SENSOR_GRID', target.shape, flush=True)
        res = scene.resample(target, resampler='native')
        res.load(['geo_color'])
        ancillary = [key for key in res.keys() if res[key].attrs.get('area') != target]
        print('ALIGN_ANCILLARY', [str(k) for k in ancillary], flush=True)
        if ancillary:
            aligned = res.resample(target, datasets=ancillary, generate=False,
                                   resampler='nearest', radius_of_influence=6000)
            for key in ancillary:
                res[key] = aligned[key]
        res.generate_possible_composites(unload=True)
    assert 'geo_color' in res
    stamp = Path(files[0]).name.split('_')
    out = ROOT/'data/exports'/f'champi_satpy_direct_{stamp[2]}T{stamp[3]}Z'
    out.mkdir(exist_ok=True)
    path = out/f'champi_geocolor_{view}.png'
    print('SAVE', path, flush=True)
    res.save_dataset('geo_color', filename=str(path), writer='simple_image', fill_value=0)
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        assert im.size == (target.width, target.height)
        preview = im.copy()
        preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        preview.save(out/f'{view}_preview.jpg', quality=94)
    info = dict(satpy_version=satpy.__version__, composite='geo_color', reader='ahi_hsd',
        nominal_utc=f'{stamp[2][:4]}-{stamp[2][4:6]}-{stamp[2][6:]}T{stamp[3][:2]}:{stamp[3][2:]}:00Z',
        start_utc=str(res['geo_color'].attrs.get('start_time')), end_utc=str(res['geo_color'].attrs.get('end_time')),
        shape=[target.height, target.width], projection=target.crs.to_string(), extent=list(target.area_extent),
        source=str(raw.resolve()), sha256=hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
        method=('Satpy stock geo_color and enhancement; nearest orthographic reprojection' if view == 'front'
                else 'Satpy stock geo_color and enhancement; native sensor aggregation/repetition, nearest ancillary reprojection'),
        limits='B03 500m, B01/B02/B04 1km, IR 2km; background is static 2016 Black Marble at 3km. Full disk covers one observed hemisphere only. Front projection center is a framing choice, not an observed cyclone fix.')
    (out/f'{view}_metadata.json').write_text(json.dumps(info, indent=2))
    print('DONE', path, flush=True)


def regional_from_disk(raw):
    """Reference-like regional framing, exact source pixels without enlargement."""
    from PIL import Image
    from pyproj import CRS, Transformer
    Image.MAX_IMAGE_PIXELS = None
    first = next(raw.glob('HS_H09_*'))
    stamp = first.name.split('_')
    out = ROOT/'data/exports'/f'champi_satpy_direct_{stamp[2]}T{stamp[3]}Z'
    info = json.loads((out/'disk_metadata.json').read_text())
    projection = CRS.from_user_input(info['projection'])
    x, y = Transformer.from_crs('EPSG:4326', projection, always_xy=True).transform(130.7, 22)
    left, bottom, right, top = info['extent']
    h, w = info['shape']
    dx, dy = (right-left)/w, (top-bottom)/h
    px, py = round((x-left)/dx-2400), round((top-y)/dy-1588)
    box = (px, py, px+4800, py+3176)
    assert 0 <= px < px+4800 <= w and 0 <= py < py+3176 <= h
    path = out/'champi_geocolor_regional.png'
    with Image.open(out/'champi_geocolor_disk.png') as full:
        image = full.crop(box)
        image.save(path)
        image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        image.save(out/'regional_preview.jpg', quality=94)
    with Image.open(path) as image:
        image.verify()
    info.update(shape=[3176, 4800], source=str((out/'champi_geocolor_disk.png').resolve()),
        pixel_crop_xyxy=list(box), extent=[left+px*dx, top-(py+3176)*dy, left+(px+4800)*dx, top-py*dy],
        method='Exact pixel crop of Satpy GeoColor full disk; no rescaling, added lighting or project processing',
        sha256=hashlib.file_digest(path.open('rb'), 'sha256').hexdigest())
    (out/'regional_metadata.json').write_text(json.dumps(info, indent=2))
    print('DONE', path, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--view', choices=['disk', 'front', 'regional'])
    parser.add_argument('--raw', type=Path)
    args = parser.parse_args()
    if args.view:
        render(args.raw, args.view)
    else:
        acquire()
