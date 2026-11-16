"""Compare two actual native crop tasks serially and as isolated processes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import subprocess
import sys
import time
import numpy as np
import rasterio

root=Path(__file__).resolve().parents[1]
project=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
out=project/'reports/process_parallelism_benchmark'
out.mkdir(exist_ok=False)
utc=json.loads((project/'reports/status.json').read_text())['utc']
records=[]

def job(label):
    folder=out/label
    command=[sys.executable,'-X','utf8',str(root/'scripts/benchmark_h9_compute_workers.py'),
             '--utc',utc,'--runs','6','--output',str(folder)]
    with (out/(label+'.log')).open('w',encoding='utf-8') as stream:
        subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,check=True)
    result=json.loads((folder/'results.json').read_text())['records'][0]
    with rasterio.open(folder/'workers_6_0.tif') as src:
        data=src.read();grid=(src.transform,src.crs)
    return data,grid,result

start=time.monotonic();baseline=job('serial_a');second=job('serial_b')
serial=time.monotonic()-start
assert np.array_equal(baseline[0],second[0]) and baseline[1]==second[1]
print('SERIAL_TWO_TASKS',serial,flush=True)
start=time.monotonic()
with ThreadPoolExecutor(max_workers=2) as pool:
    tasks=list(pool.map(job,['parallel_a','parallel_b']))
parallel=time.monotonic()-start
for data,grid,result in tasks:
    assert np.array_equal(data,baseline[0]) and grid==baseline[1]
report=dict(utc=utc,serial_two_tasks_seconds=serial,parallel_two_tasks_seconds=parallel,
    time_reduction=1-parallel/serial,identical_actual_rgba_and_georeferencing=True,
    serial_records=[baseline[2],second[2]],parallel_records=[t[2] for t in tasks],
    limits='Two independent identical real native crops including process/graph startup; cold per-job caches; production active; no full-scan speed claim')
(out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('ACTUAL_PROCESS_PARALLELISM',json.dumps(report),flush=True)
