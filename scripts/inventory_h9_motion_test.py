"""Read-only provider inventory for the explicitly requested H9 six-hour test."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges.catalog import s3_client, list_objects
from ges_next.isolation import require_writable

root = Path(__file__).resolve().parents[1]
out = require_writable(root/'data/projects/H9_20261020_UTCminus7_1100_1700')
out.mkdir(parents=True, exist_ok=True)
bands = ['B01', 'B02', 'B03', 'B04', 'B07', 'B13']
start = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
stamps = [start+timedelta(minutes=10*i) for i in range(37)]

def inspect(stamp):
    prefix = f'AHI-L1b-FLDK/{stamp:%Y/%m/%d/%H%M}/'
    objects = list_objects(s3_client(), 'noaa-himawari9', prefix)
    selected, missing = [], []
    for band in bands:
        for segment in range(1, 11):
            choices = [o for o in objects if f'_{band}_FLDK_' in o['Key'] and f'_S{segment:02}10.DAT' in o['Key']]
            if len(choices) != 1:
                missing.append(dict(band=band, segment=segment, matches=len(choices)))
            else:
                obj = choices[0]
                selected.append(dict(key=obj['Key'], bytes=obj['Size'], etag=obj['ETag'], band=band, segment=segment))
    print(stamp.isoformat(), len(selected), 'objects', sum(o['bytes'] for o in selected), flush=True)
    return dict(utc=stamp.isoformat().replace('+00:00', 'Z'), prefix=prefix, objects=selected, missing=missing)

with ThreadPoolExecutor(max_workers=6) as pool:
    scenes = list(pool.map(inspect, stamps))
total = sum(o['bytes'] for s in scenes for o in s['objects'])
report = dict(user_start='2026-10-20T11:00:00-07:00', user_end='2026-10-20T17:00:00-07:00',
    start_utc=stamps[0].isoformat(), end_utc=stamps[-1].isoformat(), cadence_minutes=10,
    satellite='himawari9', bucket='noaa-himawari9', requested_nodes=37,
    complete_nodes=sum(not s['missing'] for s in scenes), provider_bytes=total,
    local_free_bytes=shutil.disk_usage(root).free, external_F_available=Path('F:/').exists(),
    downloads=0, scenes=scenes)
(out/'provider_inventory.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('INVENTORY_COMPLETE', json.dumps({k:v for k,v in report.items() if k!='scenes'}), flush=True)
