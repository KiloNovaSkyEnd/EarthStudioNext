"""Lossless native-grid float32 band cache; no common 8K intermediate."""
from contextlib import ExitStack
import gc
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.windows import Window
from satpy import Scene
from .archive import target_for, sha
from .project import save, check_disk,observation_interval
from .io_paths import reader_paths

RECIPES = {
    'himawari8': ('ahi_hsd', ['B01','B02','B03','B04','B07','B13']),
    'goes16': ('abi_l1b', ['C01','C02','C03','C07','C13']),
    'goes17': ('abi_l1b', ['C01','C02','C03','C07','C13']),
    'meteosat_zero': ('seviri_l1b_native', ['VIS006','VIS008','IR_039','IR_108']),
    'meteosat_iodc': ('seviri_l1b_native', ['VIS006','VIS008','IR_039','IR_108']),
}


def convert_scene(root, plan, descriptor):
    root = Path(root)
    scene_id, sensor = descriptor['scene_id'], descriptor['sensor']
    dest = root / 'processed' / 'native' / scene_id
    completed = dest / 'bands.json'
    if completed.is_file():
        old = json.loads(completed.read_text(encoding='utf-8'))
        if all((dest / b['file']).is_file() and (dest / b['file']).stat().st_size == b['bytes'] for b in old['bands'].values()):
            return completed
        raise ValueError('Committed native cache differs from manifest; preserved')
    records = [r for r in plan['records'] if r['scene_id'] == scene_id]
    files = [target_for(root, r) for r in records]
    if not files or any(not p.is_file() or p.stat().st_size != r['size'] for p, r in zip(files, records)):
        raise FileNotFoundError('Complete verified native scene not archived yet: '+scene_id)
    reader, names = RECIPES[sensor]
    inputs = reader_paths(root, scene_id, files) if sensor.startswith('goes') else files
    scene = Scene(reader=reader, filenames=[str(p) for p in inputs])
    scene.load(names)
    dest.mkdir(parents=True, exist_ok=True)
    result = {'scene_id': scene_id, 'sensor': sensor, 'bands': {},
              'source_files': [str(p) for p in files], 'sampling': 'native unresampled grid',
              'quality': 'ABI delivered DQF==0 per band; other readers native masking; no invented coverage'}
    for name in names:
        data = scene[name]
        area = data.attrs['area']
        units = data.attrs.get('units')
        expected = 'K' if name in ('B07','B13','C07','C13','IR_039','IR_108') else '%'
        if units != expected:
            raise ValueError(f'Unexpected {name} units {units}; expected {expected}')
        if area.shape != data.shape or not area.crs.coordinate_operation.method_name.startswith('Geostationary'):
            raise ValueError('Native geostationary grid required')
        output = dest / f'{name}.tif'
        meta_path = output.with_suffix('.json')
        if output.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if output.stat().st_size != meta['bytes']:
                raise ValueError('Native band cache size mismatch')
            result['bands'][name] = meta
            continue
        if output.exists():
            # Interrupted old versions committed TIFF before serializing numpy
            # metadata. Retain that derived file; rebuild a verified replacement.
            from datetime import datetime, timezone
            recovery = output.with_name(output.stem+'.unindexed.'+
                datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.tif')
            output.rename(recovery)
            print('PRESERVED_UNINDEXED',str(recovery),flush=True)
        check_disk(root, area.width*area.height*4)
        temporary = output.with_suffix('.tif.part')
        with ExitStack() as stack:
            quality = None
            if sensor.startswith('goes'):
                from netCDF4 import Dataset
                source = next(p for p in inputs if f'{name}_G' in p.name)
                dataset = stack.enter_context(Dataset(str(source)))
                quality = dataset['DQF']
                if quality.shape != data.shape:
                    raise ValueError('Per-band quality grid mismatch')
            writer = stack.enter_context(rasterio.open(temporary, 'w', driver='GTiff',
                width=area.width, height=area.height, count=1, dtype='float32', crs=area.crs,
                transform=from_bounds(*area.area_extent, area.width, area.height), nodata=np.nan,
                tiled=True, blockxsize=512, blockysize=512, compress='zstd', predictor=3,
                zstd_level=3, BIGTIFF='IF_SAFER', num_threads=2))
            finite, total = 0, 0
            samples = []
            for y in range(0, area.height, 512):
                stop = min(y+512, area.height)
                values = np.asarray(data.isel(y=slice(y, stop)).compute(scheduler='threads', num_workers=2).values, np.float32)
                if quality is not None:
                    q = np.ma.filled(quality[y:stop, :], 255)
                    values = np.where(q == 0, values, np.nan)
                finite += int(np.isfinite(values).sum())
                total += values.size
                writer.write(values, 1, window=Window(0, y, area.width, stop-y))
                if len(samples) < 5:
                    x = area.width//2
                    samples.append((y, x, float(values[0, x])))
        temporary.replace(output)
        # Lossless compressed file must reproduce the actual computed values.
        with rasterio.open(output) as check:
            for y, x, expected_value in samples:
                value = float(check.read(1, window=Window(x, y, 1, 1))[0, 0])
                if not (value == expected_value or (np.isnan(value) and np.isnan(expected_value))):
                    raise ValueError('Lossless native cache validation failed')
        start, end = observation_interval(data.attrs)
        meta = {'file': output.name, 'bytes': output.stat().st_size, 'sha256': sha(output),
            'shape': list(area.shape), 'extent': list(area.area_extent), 'crs_wkt': area.crs.to_wkt(),
            'units': units, 'wavelength_um': list(data.attrs['wavelength']),
            'pixel_size_m': [abs(float(area.pixel_size_x)), abs(float(area.pixel_size_y))],
            'platform': data.attrs.get('platform_name'), 'actual_start_utc': start, 'actual_end_utc': end,
            'finite_pixels': finite, 'total_pixels': total, 'lossless_probe_passed': True,
            'native_resolution_preserved': True}
        save(meta_path, meta)
        result['bands'][name] = meta
        print('NATIVE', sensor, name, area.width, area.height, meta['bytes'], 'bytes', flush=True)
    save(completed, result)
    del scene
    gc.collect()
    return completed
