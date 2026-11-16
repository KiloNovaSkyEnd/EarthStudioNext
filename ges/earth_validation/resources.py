"""Measured host headroom, bounded concurrency and low-rate task telemetry."""
from contextlib import contextmanager
from threading import Event, Thread
from datetime import datetime,timezone
import os
import time
import psutil
from .project import save_report

GIB = 1024 ** 3
RAM_RESERVE = 6 * GIB
GPU_POOL_LIMIT = 2 * GIB
gpu_sample = {}
spill_sample = {}


def commit_usage():
    """Windows commit exhaustion can occur even with physical RAM available."""
    if os.name!='nt': return {}
    import ctypes
    from ctypes import wintypes
    class Information(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),*[(name,ctypes.c_size_t) for name in
            ('CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable',
             'SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')],
            ('HandleCount',wintypes.DWORD),('ProcessCount',wintypes.DWORD),('ThreadCount',wintypes.DWORD)]
    item=Information(); item.cb=ctypes.sizeof(item)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(item),item.cb):
        raise ctypes.WinError()
    return {'used_bytes':item.CommitTotal*item.PageSize,'limit_bytes':item.CommitLimit*item.PageSize,
            'available_bytes':(item.CommitLimit-item.CommitTotal)*item.PageSize}


def page_workers():
    # Allow 512MiB per page in addition to a 6GiB OS/application reserve.
    # A single job remains possible under pressure; this is admission control,
    # not a hard cap on external programs or on Satpy's intermediate arrays.
    headroom = psutil.virtual_memory().available - RAM_RESERVE
    return max(1, min(4, int(headroom // (512 * 1024 ** 2))))


@contextmanager
def monitor(root):
    stop = Event()
    process = psutil.Process()
    began = time.monotonic()
    def record():
        process.cpu_percent()
        while not stop.is_set():
            memory = psutil.virtual_memory()
            usage = process.memory_info()
            cpu = process.cpu_times()
            io = process.io_counters()
            save_report(root/'reports/resource_usage.json', {
                'pid': os.getpid(), 'elapsed_seconds': time.monotonic()-began,
                'updated_utc': datetime.now(timezone.utc).isoformat(),
                'process_rss_bytes': usage.rss, 'system_available_bytes': memory.available,
                'process_peak_rss_bytes': getattr(usage,'peak_wset',usage.rss),
                'system_commit': commit_usage(),
                'system_total_bytes': memory.total, 'process_cpu_core_percent': process.cpu_percent(),
                'process_cpu_seconds': cpu.user+cpu.system,
                'process_read_bytes': io.read_bytes, 'process_write_bytes': io.write_bytes,
                'os_reserve_target_bytes': RAM_RESERVE,
                'page_workers_now': page_workers(), 'gpu_pool_limit_bytes': GPU_POOL_LIMIT,
                'gpu_fusion': gpu_sample.copy(),
                'science_spill': spill_sample.copy(),
                'limits': 'CPU percent can exceed 100 across cores; I/O includes cached reads. Targets are not OS hard caps.'})
            stop.wait(5)
    thread = Thread(target=record, daemon=True, name='earth-resource-monitor')
    thread.start()
    try:
        yield
    finally:
        stop.set(); thread.join(timeout=6)
