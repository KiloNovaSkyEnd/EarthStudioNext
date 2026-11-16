"""Bounded CUDA backend for finished-pixel fusion; Satpy recipes stay untouched."""
from functools import lru_cache
from threading import Lock
from .resources import GPU_POOL_LIMIT
from . import resources
from time import perf_counter

_fusion_lock=Lock()


def release_idle():
    """Hand unused science allocations back before another process renders."""
    import cupy as cp
    with _fusion_lock:
        cp.get_default_memory_pool().free_all_blocks()
        cp.get_default_pinned_memory_pool().free_all_blocks()
        resources.gpu_sample.update(pool_reserved_bytes=cp.get_default_memory_pool().total_bytes())


@lru_cache(maxsize=1)
def device():
    import cupy as cp
    # Execute a kernel: driver enumeration alone is not evidence of working CUDA.
    assert int(cp.asnumpy(cp.arange(16).sum())) == 120
    properties=cp.cuda.runtime.getDeviceProperties(0)
    name=properties['name']
    return {'backend':'cuda','device':name.decode() if isinstance(name,bytes) else name,
            'total_vram_bytes':properties['totalGlobalMem'],
            'scope':'Geographic fusion only; stock Satpy and GDAL remain CPU'}


def fuse_cuda(sources,longitude,latitude,feather_degrees,latitude_limit):
    import cupy as cp
    from .fusion import _fuse
    device()
    # Serialize uploads/kernels/downloads while CPU page preparation overlaps.
    if longitude.size>4096*4096:
        raise ValueError('CUDA fusion requires bounded tiles, not a full native disk')
    with _fusion_lock:
        began=perf_counter()
        pool=cp.get_default_memory_pool()
        pool.set_limit(size=GPU_POOL_LIMIT)
        # Reuse bounded allocations across pages; do not cudaFree every page.
        result=_fuse([(cp.asarray(pixels),lon0) for pixels,lon0 in sources],
                     cp.asarray(longitude),cp.asarray(latitude),feather_degrees,latitude_limit,cp)
        output=tuple(cp.asnumpy(value) for value in result)
        free,total=cp.cuda.runtime.memGetInfo()
        resources.gpu_sample.update({'last_fusion_seconds':perf_counter()-began,
            'pool_reserved_bytes':pool.total_bytes(),'device_free_bytes':free,
            'device_total_bytes':total})
        return output
