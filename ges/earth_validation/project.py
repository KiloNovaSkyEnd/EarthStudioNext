"""Explicit time window, bounded storage and atomic experiment records."""
from datetime import timedelta, timezone
from pathlib import Path
import json
import shutil
import os
import tempfile
import time
from ges.catalog import utc_time


def json_scalar(value):
    # Reader attributes (notably ABI wavelength) can contain numpy.float32.
    import numpy as np
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f'Unsupported metadata type: {type(value).__name__}')


def observation_interval(attrs):
    """Actual reader scan times; SEVIRI nominal slots are not scan intervals."""
    times=attrs.get('time_parameters',{})
    def iso(value):
        if value is None: return None
        if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    return (iso(times.get('observation_start_time',attrs.get('start_time'))),
            iso(times.get('observation_end_time',attrs.get('end_time'))))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, default=json_scalar)
    # Readers on Windows may transiently deny delete-sharing. Unique temporary
    # names also prevent independent reporters from replacing each other's temp.
    descriptor,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    temp=Path(name)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream: stream.write(payload)
    for attempt in range(12):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt==11: raise
            time.sleep(min(.025*(attempt+1),.2))


def save_report(path,value):
    """Best-effort telemetry must not invalidate an otherwise valid image."""
    try:
        save(path,value)
        return True
    except OSError as error:
        import logging
        logging.getLogger(__name__).warning('Report update delayed: %s: %s',path,error)
        return False


def initialize(root):
    root = Path(root).resolve()
    for name in ('raw', 'processed', 'exports', 'reports', 'scratch'):
        (root / name).mkdir(parents=True, exist_ok=True)
    config = root / 'project.json'
    if not config.exists():
        save(config, {'start_utc': '2022-08-31T17:00:00Z', 'end_utc': '2022-09-01T05:00:00Z',
            'requested_local': '2022-08-31 11:00..23:00, fixed UTC-06:00',
            'interval_minutes': 10, 'raw_budget_bytes': 300_000_000_000,
            'workspace_budget_bytes': 1_000_000_000_000, 'reserve_free_bytes': 150_000_000_000,
            'scope': 'Nonpolar five-source layout; preserve missing observations and actual scan intervals',
            'native_archive': True, 'preview_is_proxy': True,
            'not_claimed': ['uniform true color in historical SEVIRI', 'retrieved 3D cloud interiors',
                            'zero resampling loss', 'complete seamless coverage before pixel QA']})
    return json.loads(config.read_text(encoding='utf-8'))


def timeline(config):
    start, end = utc_time(config['start_utc']), utc_time(config['end_utc'])
    if end < start:
        raise ValueError('Reversed UTC interval')
    return [start + timedelta(minutes=i) for i in range(0, int((end-start).total_seconds()/60)+1,
                                                      config['interval_minutes'])]


def check_disk(root, incoming=0):
    root = Path(root)
    config = initialize(root)
    free = shutil.disk_usage(root).free
    if incoming < 0 or free-incoming < config['reserve_free_bytes']:
        raise RuntimeError(f'Insufficient working-volume space: free={free}, incoming={incoming}')
    return free
