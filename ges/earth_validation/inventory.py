"""List actual native-resolution NOAA bands and historical SEVIRI scans."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import json
import re
import requests
from ges.catalog import s3_client, list_objects
from ges.meteosat import SEARCH_URL, COLLECTIONS, select_observation
from ges.meteosat_download import probe_bytes
from ges.eumetsat_auth import authenticated_token
from .project import initialize, timeline, save, check_disk

AHI = ('B01', 'B02', 'B03', 'B04', 'B07', 'B13')
ABI = ('C01', 'C02', 'C03', 'C07', 'C13')


def iso(stamp):
    return stamp.isoformat().replace('+00:00', 'Z')


def ahi_records(stamp):
    bucket = 'noaa-himawari8'
    objects = list_objects(s3_client(), bucket, f'AHI-L1b-FLDK/{stamp:%Y/%m/%d/%H%M}/')
    records = []
    for band in AHI:
        selected = [o for o in objects if f'_{band}_FLDK_' in o['Key']]
        segments = [int(re.search(r'_S(\d{2})10\.DAT', o['Key']).group(1)) for o in selected]
        if sorted(segments) != list(range(1, 11)):
            raise ValueError(f'Incomplete AHI native band {iso(stamp)} {band}')
        records.extend({'provider': 's3', 'sensor': 'himawari8', 'bucket': bucket,
            'key': o['Key'], 'size': o['Size'], 'etag': o['ETag'], 'band': band,
            'nominal_utc': iso(stamp), 'scene_id': f'himawari8_{stamp:%Y%m%dT%H%MZ}'} for o in selected)
    return records


def abi_hour(satellite, hour):
    objects = list_objects(s3_client(), f'noaa-{satellite}', f'ABI-L1b-RadF/{hour:%Y/%j/%H}/')
    result = []
    for o in objects:
        match = re.search(r'M\d(C\d{2})_G\d+_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})(\d*)_', o['Key'])
        if not match or match[1] not in ABI:
            continue
        year, day, hh, mm, ss = map(int, match.groups()[1:6])
        stamp = hour.replace(year=year, month=1, day=1, hour=hh, minute=mm, second=ss,
                             microsecond=int((match[7] or '0').ljust(6, '0')[:6])) + timedelta(days=day-1)
        result.append({'provider': 's3', 'sensor': satellite, 'bucket': f'noaa-{satellite}',
            'key': o['Key'], 'size': o['Size'], 'etag': o['ETag'], 'band': match[1],
            'actual_start_utc': iso(stamp), '_stamp': stamp})
    return result


def build(root):
    root = Path(root)
    config = initialize(root)
    stamps = timeline(config)
    records, scenes, failures = [], [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [(t, pool.submit(ahi_records, t)) for t in stamps]
        for stamp, future in futures:
            try:
                rows = future.result()
                records.extend(rows)
                scenes.append({'sensor': 'himawari8', 'nominal_utc': iso(stamp), 'scene_id': rows[0]['scene_id']})
            except Exception as error:
                failures.append({'sensor': 'himawari8', 'nominal_utc': iso(stamp), 'error': str(error)})
        hours = sorted(set(t.replace(minute=0, second=0, microsecond=0) for t in stamps))
        futures = [(sat, pool.submit(abi_hour, sat, hour)) for sat in ('goes16', 'goes17') for hour in hours]
        catalogs = {'goes16': [], 'goes17': []}
        for sat, future in futures:
            catalogs[sat].extend(future.result())
    for satellite, catalog in catalogs.items():
        for stamp in stamps:
            selected = []
            for band in ABI:
                options = [r for r in catalog if r['band'] == band and abs((r['_stamp']-stamp).total_seconds()) < 90]
                if len(options) != 1:
                    failures.append({'sensor': satellite, 'nominal_utc': iso(stamp), 'band': band,
                                     'error': f'{len(options)} matching native L1b files'})
                    continue
                row = {k: v for k, v in options[0].items() if k != '_stamp'}
                row.update(nominal_utc=iso(stamp), scene_id=f'{satellite}_{stamp:%Y%m%dT%H%MZ}')
                selected.append(row)
            if len(selected) == len(ABI):
                records.extend(selected)
                scenes.append({'sensor': satellite, 'nominal_utc': iso(stamp), 'scene_id': selected[0]['scene_id']})
    token = authenticated_token()
    for service in ('zero', 'iodc'):
        # 12h yields <100 scans; include boundaries and reject truncated responses.
        response = requests.get(SEARCH_URL, params={'format': 'json', 'pi': COLLECTIONS[service],
            'dtstart': iso(stamps[0]-timedelta(minutes=16)),
            'dtend': iso(stamps[-1]+timedelta(minutes=16)), 'c': 100}, timeout=60)
        response.raise_for_status()
        data = response.json()
        save(root / 'reports' / f'{service}_catalog.json', data)
        unique = {}
        for stamp in stamps:
            try:
                candidate = select_observation(data, stamp, service, 10)
                scene_id = 'meteosat_' + service + '_' + candidate['product_id']
                scenes.append({'sensor': 'meteosat_'+service, 'nominal_utc': iso(stamp), 'scene_id': scene_id,
                               'scan_start_utc': candidate['scan_start_utc'], 'scan_end_utc': candidate['scan_end_utc']})
                unique[scene_id] = candidate
            except Exception as error:
                failures.append({'sensor': service, 'nominal_utc': iso(stamp), 'error': str(error)})
        for scene_id, candidate in unique.items():
            size = probe_bytes(candidate, token)
            records.append({'provider': 'eumetsat', 'sensor': 'meteosat_'+service, 'scene_id': scene_id,
                'size': size, 'candidate': candidate, 'band': 'native_all_channels',
                'nominal_utc': candidate['scan_start_utc'], 'filename': candidate['product_id']+'.nat'})
        print('SEVIRI verified inventory', service, len(unique), flush=True)
    total = sum(row['size'] for row in records)
    if total > config['raw_budget_bytes']:
        raise RuntimeError(f'Raw inventory {total} exceeds project ceiling {config["raw_budget_bytes"]}')
    check_disk(root, total)
    plan = {'config': config, 'frames': [iso(t) for t in stamps], 'records': records, 'scenes': scenes,
            'total_raw_bytes': total, 'failures': failures, 'complete_inventory': not failures,
            'native_resolution_products': True, 'uses_2km_MCMIPF_for_GOES': False}
    save(root / 'inventory.json', plan)
    print('INVENTORY', len(stamps), 'frames', len(records), 'objects', total, 'bytes', len(failures), 'gaps', flush=True)
    return plan
