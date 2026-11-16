"""Kernel-owned queue lock: released on cancellation/crash, no stale PID heuristics."""
from contextlib import contextmanager
import os
from pathlib import Path


class QueueBusyError(ValueError):
    def __init__(self,path):
        self.path=Path(path).resolve()
        super().__init__('资源正在由另一任务使用：'+str(path))


@contextmanager
def exclusive(path,wait=False,timeout=600):
    with open(path,'a+b') as stream:
        stream.seek(0,2)
        if not stream.tell():stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            import time
            began=time.monotonic()
            while True:
                try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError as error:
                    if not wait or time.monotonic()-began>=timeout:raise QueueBusyError(path) from error
                    time.sleep(.1)
        else:
            import fcntl
            try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|(0 if wait else fcntl.LOCK_NB))
            except BlockingIOError as error:raise QueueBusyError(path) from error
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
