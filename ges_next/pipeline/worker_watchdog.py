"""Detect stalled owned children using work progress, not telemetry heartbeats."""
import time
import psutil

class WorkerStalledError(RuntimeError):pass

class Watchdog:
    def __init__(self,stall_seconds=900,total_seconds=3600,now=None):
        self.stall_seconds=stall_seconds;self.total_seconds=total_seconds
        self.began=self.progress=time.monotonic() if now is None else now
        self.phase=None;self.tasks=None;self.io=0;self.cpu=0
    def observe(self,now,phase=None,tasks=None,io=None,cpu=None):
        if phase is not None and phase!=self.phase:self.phase=phase;self.progress=now
        if tasks is not None and tasks!=self.tasks:self.tasks=tasks;self.progress=now
        # During Dask computation the resource-monitor thread can keep consuming
        # CPU/writing JSON even when actual computation has stopped. Only task
        # completion or a genuine phase transition resets that timer.
        if self.tasks is None:
            if io is not None and io-self.io>=1024**2:self.progress=now;self.io=io
            if cpu is not None and cpu-self.cpu>=1:self.progress=now;self.cpu=cpu
        if now-self.began>=self.total_seconds:return 'Owned worker exceeded bounded wall-clock limit'
        if now-self.progress>=self.stall_seconds:return 'Owned worker made no scientific task/phase progress'
        return None

def stop_owned_tree(process,created,tracked=None):
    if created is None:return False
    try:
        root=psutil.Process(process.pid)
        if abs(root.create_time()-created)<=.01:
            for child in root.children(recursive=True):
                if tracked is not None:tracked[child.pid]=child.create_time()
    except psutil.NoSuchProcess:pass
    stopped=False
    for pid,born in (tracked or {}).items():
        try:
            child=psutil.Process(pid)
            if abs(child.create_time()-born)<=.01:child.kill();stopped=True
        except psutil.NoSuchProcess:pass
    try:
        root=psutil.Process(process.pid)
        if abs(root.create_time()-created)<=.01:process.kill();stopped=True
    except psutil.NoSuchProcess:pass
    return stopped
