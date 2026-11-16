"""Isolated same-source packed-vs-mmap night input experiment; no activation."""
import argparse
from collections import defaultdict
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Import bootstrap before Satpy so this benchmark matches production constants.
from ges.earth_validation import stock, night_packing, resources
from ges.earth_validation.spill import bounded_compute
from ges_next.h9_decode import decode_originals
from ges_next.isolation import require_writable
import numpy as np
import rasterio
import satpy
from satpy import Scene
import yaml
from dask.callbacks import Callback


class TaskTiming(Callback):
    def __init__(self):
        self.starts = {}; self.groups = defaultdict(lambda: [0, 0.0])
        super().__init__()
    def _start(self, dsk):
        self.graph_tasks = len(dsk)
    def _pretask(self, key, dsk, state):
        self.starts[key] = time.perf_counter()
    def _posttask(self, key, result, dsk, state, worker_id):
        prefix = str(key[0] if isinstance(key, tuple) else key).rsplit('-', 1)[0]
        item = self.groups[prefix]
        item[0] += 1; item[1] += time.perf_counter() - self.starts.pop(key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--utc', default='20261020T1500Z')
    parser.add_argument('--runs', default='packed,mmap,mmap,packed')
    args = parser.parse_args()
    p = args.project.resolve(); out = require_writable(args.output)
    out.mkdir(exist_ok=False, parents=True)
    if __import__('shutil').disk_usage(out).free < 24*1024**3:
        raise RuntimeError('Insufficient bounded experiment reserve')
    sources = sorted((p/'raw'/args.utc).glob('*.DAT.bz2'))
    if len(sources) != 60: raise ValueError('Requires retained complete sixty-file observation')
    (out/'project.json').write_text(json.dumps(dict(compute_workers=6, reserve_free_bytes=16*1024**3)))
    reference = ROOT.parent/'GlobalSatelliteEarthStudio/data/raw/reference'
    stock.configure(out)
    runtime = out/'scratch/pyspectral_runtime.yaml'
    runtime.write_text(yaml.safe_dump(dict(download_from_internet=False,
        rayleigh_dir=str(reference/'pyspectral'), rsr_dir=str(reference/'pyspectral/rsr'))))
    os.environ['PSP_CONFIG_FILE'] = str(runtime)
    os.environ['EARTHSTUDIO_H9_CUDA_CLOUDS'] = '2'
    satpy.config.set(data_dir=str(reference/'satpy_geocolor_v060'), download_aux=False,
        config_path=[str(ROOT/'ges/earth_validation/satpy_config'), str(ROOT/'ges/earth_validation/cuda_satpy_config')])
    original_packed = night_packing.packed
    baseline = None; records = []
    with tempfile.TemporaryDirectory(prefix='private_decoded_', dir=out, ignore_cleanup_errors=True) as temp:
        files = decode_originals(sources, Path(temp), workers=4)
        for index, mode in enumerate(args.runs.split(',')):
            if mode not in ('packed', 'mmap', 'geometry_mmap'): raise ValueError('Unknown representation')
            night_packing.packed = original_packed if mode == 'packed' else lambda values: values
            # Sensor-angle caching is intentionally disabled: Satpy sanitizes
            # satellite position/time, which requires separate parity qualification.
            satpy.config.set(cache_lonlats=mode=='geometry_mmap', cache_sensor_angles=False,
                             cache_dir=str(out/'geometry_cache'))
            start = time.perf_counter()
            scene = Scene(reader='ahi_hsd', filenames=[str(f) for f in files])
            scene.load(['B01','B02','B03','B04','B07','B13'])
            opened = time.perf_counter()
            target = scene['B03'].attrs['area'][5500:11000,5500:11000]
            result, area = stock.compose(scene, target,
                p/'raw/references/blackmarble_2016_500m/global_500m.vrt', reference,
                native=True, native_tile=True, night_cache=p/'shared_static/night_grids')
            planned = time.perf_counter(); output = out/f'{index}_{mode}.tif'
            timing = TaskTiming()
            before = resources.gpu_sample.copy()
            with bounded_compute(out, workers=6), timing:
                result.save_dataset('geo_color', filename=str(output), writer='geotiff', dtype=np.uint8,
                    compress='DEFLATE', tiled=True, blockxsize=256, blockysize=256, predictor=2,
                    zlevel=6, num_threads=4, include_scale_offset_tags=False)
            ended = time.perf_counter()
            with rasterio.open(output) as src: actual = (src.read(), src.transform, src.crs)
            if baseline is None: baseline = actual
            equal = np.array_equal(actual[0], baseline[0]) and actual[1:] == baseline[1:]
            rec = dict(mode=mode, open_seconds=opened-start, planning_seconds=planned-opened,
                compute_write_seconds=ended-planned, inclusive_seconds=ended-start,
                exact_rgba_grid_parity=equal, graph_tasks=timing.graph_tasks,
                gpu_delta={k: resources.gpu_sample.get(k,0)-before.get(k,0)
                    for k in ('calls','pixels','total_kernel_ms','total_transfer_and_compute_seconds')},
                task_groups=sorted([dict(prefix=k,count=v[0],summed_task_seconds=v[1])
                    for k,v in timing.groups.items()], key=lambda x:-x['summed_task_seconds'])[:25])
            records.append(rec)
            (out/'results.json').write_text(json.dumps(dict(utc=args.utc, shape=list(actual[0].shape),
                records=records, limits='Active production competes for resources; one full native tile. '
                'Task durations overlap and include waits. mmap changes only private experiment I/O representation; '
                'no production code/config changed.'), indent=2))
            print(json.dumps({k:v for k,v in rec.items() if k!='task_groups'}), flush=True)
            if not equal: raise ValueError('Pixel/grid parity failed')
            del result, scene, actual; gc.collect()
    night_packing.packed = original_packed


if __name__ == '__main__':
    main()
