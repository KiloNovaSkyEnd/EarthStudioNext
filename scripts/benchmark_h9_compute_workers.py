"""Bounded real H9 native crop, same scientific graph with2/4/6 CPU threads."""
import gc
import json
import os
from pathlib import Path
import sys
import time
import argparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges_next.isolation import require_writable
from ges.earth_validation import stock
from ges.earth_validation.spill import bounded_compute
from ges.earth_validation.project import save
import numpy as np
import psutil
import rasterio
from satpy import Scene
import satpy,yaml

project=ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--utc',default=None)
parser.add_argument('--runs',default='2,4,6,2')
parser.add_argument('--output',type=Path,default=project/'reports/compute_workers_benchmark')
parser.add_argument('--static-cache',type=Path,default=None)
args=parser.parse_args()
out=require_writable(args.output)
out.mkdir(exist_ok=True,parents=True)
if (out/'results.json').exists():raise FileExistsError('Preserve prior measured benchmark')
utc=args.utc or json.loads((project/'reports/status.json').read_text())['utc']
from datetime import datetime
stamp=datetime.fromisoformat(utc.replace('Z','+00:00'))
reference=ROOT.parent/'GlobalSatelliteEarthStudio/data/raw/reference'
folders=list((project/'scratch').glob(f'decoded_{stamp:%H%M}_*'))
if len(folders)!=1:raise ValueError('Active decoded original required; no downloading/re-decoding for benchmark')
files=sorted(folders[0].glob(f'HS_H09_{stamp:%Y%m%d_%H%M}_*.DAT'))
if len(files)!=60:raise ValueError('Requires complete actualH9 six-band input')
save(out/'project.json',dict(reserve_free_bytes=16*1024**3))
stock.configure(out)
config=out/'scratch/pyspectral_runtime.yaml'
config.write_text(yaml.safe_dump(dict(download_from_internet=False,rayleigh_dir=str(reference/'pyspectral'),rsr_dir=str(reference/'pyspectral/rsr'))))
os.environ['PSP_CONFIG_FILE']=str(config)
satpy.config.set(data_dir=str(reference/'satpy_geocolor_v060'),download_aux=False)
scene=Scene(reader='ahi_hsd',filenames=[str(p) for p in files])
scene.load(['B01','B02','B03','B04','B07','B13'])
target=scene['B03'].attrs['area'][6500:8036,10000:11536]
began=time.monotonic()
result,target=stock.compose(scene,target,project/'raw/references/blackmarble_2016_500m/global_500m.vrt',reference,
    native=True,native_tile=True,night_cache=require_writable(args.static_cache) if args.static_cache else out/'static/night_grids')
print('BENCH_GRAPH_READY',time.monotonic()-began,flush=True)
baseline=None;records=[]
for index,workers in enumerate([int(v) for v in args.runs.split(',')]):
    path=out/f'workers_{workers}_{index}.tif'
    process=psutil.Process();cpu0=process.cpu_times();start=time.monotonic()
    with bounded_compute(out,workers=workers):
        result.save_dataset('geo_color',filename=str(path),writer='geotiff',dtype=np.uint8,compress='DEFLATE',
            tiled=True,blockxsize=256,blockysize=256,predictor=2,include_scale_offset_tags=False)
    elapsed=time.monotonic()-start;cpu=process.cpu_times()
    with rasterio.open(path) as source:
        pixels=source.read();transform=list(source.transform);crs=source.crs.to_wkt()
    if baseline is None:baseline=(pixels,transform,crs)
    equal=np.array_equal(baseline[0],pixels) and transform==baseline[1] and crs==baseline[2]
    record=dict(requested_workers=workers,seconds=elapsed,identical_rgba_and_georeferencing=equal,
        shape=list(pixels.shape),cpu_seconds=cpu.user+cpu.system-cpu0.user-cpu0.system,
        rss_bytes=process.memory_info().rss)
    from ges.earth_validation.resources import spill_sample
    record['admitted_workers']=spill_sample['admitted_workers']
    records.append(record);save(out/'results.json',dict(graph_seconds=time.monotonic()-began,records=records,
        limits='One native crop on an active production host; no whole-frame or GPU speed claim'))
    print('WORKER_BENCH',json.dumps(record),flush=True)
    if not equal:raise ValueError('Output differs; do not enable acceleration')
    gc.collect()
print('PASS_ACTUAL_NATIVE_CROP',flush=True)
