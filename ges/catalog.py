"""Anonymous NOAA S3 geostationary satellite catalog; indexes actual objects only."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

H8_TO_H9 = datetime(2022, 12, 13, 5, tzinfo=timezone.utc)
HIM_PRODUCTS = 'AHI-L1b-FLDK'
GOES_PRODUCTS = 'ABI-L2-MCMIPF'

@dataclass(frozen=True)
class Scene:
    satellite: str
    bucket: str
    prefix: str
    observed_utc: datetime
    keys: tuple[str, ...]
    total_bytes: int
    product: str
    object_sizes: tuple[int, ...] = ()

    @property
    def scene_id(self) -> str:
        return f'{self.satellite}_{self.observed_utc.strftime("%Y%m%dT%H%M%SZ")}'


def utc_time(value: str) -> datetime:
    # Explicit UTC only. Never rely on Windows local timezone.
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('日期必须包含时区，例如 2020-10-29T16:40:00Z')
    return t.astimezone(timezone.utc)


def selected_himawari(t: datetime) -> str:
    return 'himawari8' if t < H8_TO_H9 else 'himawari9'


def s3_client():
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    return boto3.client('s3', region_name='us-east-1', config=Config(signature_version=UNSIGNED,
                                                                  retries={'max_attempts': 4}))


def list_objects(s3, bucket: str, prefix: str) -> list[dict]:
    paginator = s3.get_paginator('list_objects_v2')
    result = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        result.extend(page.get('Contents', []))
    return result


def time_nearby(t: datetime, minutes: int = 20):
    rounded = t.replace(minute=(t.minute // 10) * 10, second=0, microsecond=0)
    return [rounded + timedelta(minutes=i) for i in range(-minutes, minutes+1, 10)]


def himawari_scene(s3, t: datetime, bands: tuple[str,...], tolerance_min: int = 20) -> Scene:
    """Index full-disk HSD folders; must contain all 10 segments for every requested band."""
    if any(not re.fullmatch(r'B(?:0[1-9]|1[0-6])', b) for b in bands):
        raise ValueError(f'AHI 非法波段: {bands}')
    sat = selected_himawari(t)
    bucket = f'noaa-{sat}'
    candidates = []
    for dt in time_nearby(t, tolerance_min):
        if selected_himawari(dt) != sat:
            continue
        prefix = f'{HIM_PRODUCTS}/{dt:%Y/%m/%d/%H%M}/'
        objects = list_objects(s3, bucket, prefix)
        # Require exact unique segment numbers S0110 ... S1010, not just 10 filenames.
        # Duplicate/unrelated segments must not silently pass completeness checks.
        selected = []
        complete = True
        for band in bands:
            matches = {}
            for obj in objects:
                name = Path(obj['Key']).name
                if f'_{band}_FLDK_' not in name:
                    continue
                m = re.search(r'_S(\d{2})(\d{2})\.DAT(?:\.bz2)?$', name, re.IGNORECASE)
                if not m or int(m.group(2)) != 10 or not 1 <= int(m.group(1)) <= 10:
                    continue
                idx = int(m.group(1))
                if idx in matches:  # duplicated segment means ambiguous product
                    complete = False
                    break
                matches[idx] = obj
            if not complete or set(matches) != set(range(1,11)):
                complete = False
                break
            selected.extend(matches[idx] for idx in range(1,11))
        if not complete:
            continue
        candidates.append(Scene(sat, bucket, prefix, dt, tuple(x['Key'] for x in selected),
                                sum(x['Size'] for x in selected), 'AHI-L1b-FLDK',
                                tuple(x['Size'] for x in selected)))
    if not candidates:
        raise FileNotFoundError('所选时间附近没有完整的 Himawari 全圆盘产品（每个波段需要10个分段）。可扩大窗口或更换日期。')
    return min(candidates, key=lambda s: abs((s.observed_utc-t).total_seconds()))


def goes_scene(s3, t: datetime, satellite: str, tolerance_min: int = 30) -> Scene:
    if satellite not in ('goes16','goes17','goes18','goes19'):
        raise ValueError('GOES 卫星必须是 goes16/17/18/19')
    candidates = []
    for hour_offset in (-1, 0, 1):
        dt = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=hour_offset)
        prefix = f'{GOES_PRODUCTS}/{dt:%Y}/{dt.timetuple().tm_yday:03d}/{dt:%H}/'
        for obj in list_objects(s3, f'noaa-{satellite}', prefix):
            # GOES naming encodes UTC acquisition time: _sYYYYJJJHHMMSS...
            m = re.search(r'_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})(\d*)_', Path(obj['Key']).name)
            if not m:
                continue
            year, day, hour, minute, second = map(int, m.groups()[:5])
            microsecond = int(m.group(6).ljust(6, '0')[:6] or '0')
            observed = datetime(year,1,1,tzinfo=timezone.utc) + timedelta(days=day-1,hours=hour,minutes=minute,seconds=second,microseconds=microsecond)
            if abs((observed-t).total_seconds()) <= tolerance_min*60:
                candidates.append(Scene(satellite, f'noaa-{satellite}', prefix, observed,
                                        (obj['Key'],), obj['Size'], GOES_PRODUCTS, (obj['Size'],)))
    if not candidates:
        raise FileNotFoundError(f'{satellite} 在指定时间附近没有 MCMIPF 数据。该卫星可能尚未投入使用或已退役。')
    return min(candidates, key=lambda s: abs((s.observed_utc-t).total_seconds()))


def scene_as_json(scene: Scene):
    return {'satellite':scene.satellite,'bucket':scene.bucket,'prefix':scene.prefix,
            'observed_utc':scene.observed_utc.isoformat(),'keys':list(scene.keys),
            'total_bytes':scene.total_bytes,'product':scene.product,'scene_id':scene.scene_id,
            'object_sizes':list(scene.object_sizes)}
