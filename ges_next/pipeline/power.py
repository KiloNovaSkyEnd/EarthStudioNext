"""Keep unattended production awake without changing Windows power settings."""
from contextlib import contextmanager
import os


@contextmanager
def keep_awake(report=lambda value:None, setter=None):
    if setter is None and os.name=='nt':
        import ctypes
        setter=ctypes.windll.kernel32.SetThreadExecutionState
    previous=setter(0x80000001) if setter is not None else None
    if setter is not None:
        report(dict(phase='power-guard',active=bool(previous)))
    try:yield
    finally:
        if setter is not None and previous:setter(previous)
