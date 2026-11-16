"""Explicit H9-only weather contract, separate from camera animation time."""
from datetime import datetime, timedelta, timezone
import math

def observation_times(start='2026-10-20T11:00:00-07:00', end='2026-10-20T17:00:00-07:00'):
    left, right = (datetime.fromisoformat(t) for t in (start, end))
    if any(t.tzinfo is None for t in (left, right)):
        raise ValueError('Explicit timezone required')
    left, right = left.astimezone(timezone.utc), right.astimezone(timezone.utc)
    if right < left or (right-left).total_seconds()%600 or any(t.minute%10 or t.second or t.microsecond for t in (left,right)):
        raise ValueError('Exact ten-minute interval required')
    return [left+timedelta(minutes=10*i) for i in range(int((right-left).total_seconds()/600)+1)]

def weather_index(seconds, duration=36, nodes=37):
    """Hold genuine scans; no fabricated intermediate weather or camera dependence."""
    if not math.isfinite(duration) or duration <= 0 or nodes < 2 or not math.isfinite(seconds):
        raise ValueError('Invalid playback mapping')
    return min(nodes-1, max(0, math.floor(min(1,max(0,seconds/duration))*(nodes-1)+1e-9)))

def storage_budget(provider_bytes, new_bytes, free_bytes, nodes=37):
    # 0.8GB per original disk is a forecast, not measured temporal output size.
    outputs = nodes*800_000_000
    scratch = 10_000_000_000
    reserve = 16*1024**3
    total = new_bytes+outputs+scratch+reserve
    return dict(provider_bytes=provider_bytes, new_download_bytes=new_bytes,
                native_output_forecast_bytes=outputs, scratch_bytes=scratch,
                reserve_bytes=reserve, required_free_bytes=total,
                available_free_bytes=free_bytes, sufficient=free_bytes>=total,
                estimates_are_not_actual_output_sizes=True)
