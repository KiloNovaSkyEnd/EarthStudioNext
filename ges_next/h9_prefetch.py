"""At most one exact, inventoried scan downloaded alongside native computation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import time

GIB=1024**3


def next_pending_scene(scenes, start, is_complete):
    """Skip acknowledged missing scans and already committed native masters."""
    return next((s for s in scenes[start:] if not s['missing'] and not is_complete(s)),None)


class OneScanPrefetch:
    def __init__(self, fetch_scene, check_space, report, enabled=False):
        self.fetch_scene=fetch_scene;self.check_space=check_space;self.report=report
        self.enabled=enabled;self.future=None;self.utc=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='h9-one-scan-prefetch') if enabled else None

    def start(self,scene):
        if not self.enabled or scene is None:return False
        if self.future is not None:raise RuntimeError('Previous prefetched scan must be consumed first')
        # Budget all inventoried bytes even when some are already retained.
        # Keep 4GiB for the active output/scratch in addition to the global reserve.
        incoming=sum(o['bytes'] for o in scene['objects'])
        try:self.check_space(incoming+4*GIB)
        except RuntimeError as error:
            self.report(dict(state='deferred_storage',utc=scene['utc'],error=str(error),incoming_bytes=incoming))
            return False
        self.utc=scene['utc']
        def run():
            began=time.monotonic()
            self.report(dict(state='downloading',utc=scene['utc'],incoming_bytes=incoming,
                updated_utc=datetime.now(timezone.utc).isoformat()))
            try:
                sources=self.fetch_scene(scene)
            except Exception as error:
                self.report(dict(state='failed',utc=scene['utc'],error=str(error)))
                raise
            self.report(dict(state='ready',utc=scene['utc'],files=len(sources),seconds=time.monotonic()-began,
                updated_utc=datetime.now(timezone.utc).isoformat()))
            return sources
        self.future=self.pool.submit(run)
        return True

    def take(self,scene):
        if self.future is None:return None
        if self.utc!=scene['utc']:raise ValueError('Prefetch UTC does not match the requested observation')
        began=time.monotonic()
        # Reuse the original fetch() integrity checks during download. There is
        # exactly one producer per UTC; failures propagate before decoding it.
        result=self.future.result()
        self.report(dict(state='consumed',utc=self.utc,wait_seconds=time.monotonic()-began,
            updated_utc=datetime.now(timezone.utc).isoformat()))
        self.future=None;self.utc=None
        return result

    def __enter__(self):return self

    def __exit__(self,*args):
        # Never release the project lock with a background writer still active.
        if self.pool:self.pool.shutdown(wait=True,cancel_futures=True)
