"""Control for filesystem warming after the independent-process qualification."""
from pathlib import Path
import json,subprocess,sys,time
import numpy as np
import rasterio

root=Path(__file__).resolve().parents[1]
out=root/'data/projects/H9_20261020_UTCminus7_1100_1700/reports/process_parallelism_benchmark'
report=json.loads((out/'results.json').read_text())
began=time.monotonic()
for letter in ['a','b']:
    dest=out/('serial_warm_'+letter)
    with (out/('serial_warm_'+letter+'.log')).open('w',encoding='utf-8') as stream:
        subprocess.run([sys.executable,'-X','utf8',str(root/'scripts/benchmark_h9_compute_workers.py'),
            '--utc',report['utc'],'--runs','6','--output',str(dest),'--static-cache',
            str(out/('serial_'+letter)/'static/night_grids')],stdout=stream,stderr=subprocess.STDOUT,check=True)
    with rasterio.open(dest/'workers_6_0.tif') as actual,rasterio.open(out/('serial_'+letter)/'workers_6_0.tif') as reference:
        assert np.array_equal(actual.read(),reference.read()) and actual.transform==reference.transform and actual.crs==reference.crs
elapsed=time.monotonic()-began
report.update(warm_serial_two_tasks_seconds=elapsed,warm_serial_actual_pixel_parity=True,
    conservative_time_reduction=1-report['parallel_two_tasks_seconds']/min(elapsed,report['serial_two_tasks_seconds']))
(out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('WARM_SERIAL_CONTROL',json.dumps({k:v for k,v in report.items() if k not in ['serial_records','parallel_records']}),flush=True)
