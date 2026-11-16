"""A bounded lossless ndarray cache for Dask's public local-scheduler API.

Arrays that would otherwise stay in the scheduler's result dictionary spill to
private .npy files. Reloads are copy-on-write memory maps; no quantisation or
scientific graph alteration. Non-array objects (including unpickleable KDTree
instances and open TIFF stores) stay in memory and are never serialized.
"""
from collections import OrderedDict
from collections.abc import MutableMapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import dask
import numpy as np
import json
import shutil
from itertools import islice
from .project import check_disk
from . import resources


class ArraySpillCache(MutableMapping):
    def __init__(self, folder, limit=2*1024**3, budget=None,fast_folder=None,
                 fast_limit=16*1024**3,fast_reserve=32*1024**3):
        self.folder=Path(folder); self.limit=limit; self.budget=budget
        self.fast=OrderedDict(); self.slow={}; self.weights={}
        self.memory_bytes=0; self.disk_bytes=0; self.written_bytes=0; self.sequence=0
        self.fast_folder=Path(fast_folder) if fast_folder else None
        self.fast_limit=fast_limit; self.fast_reserve=fast_reserve; self.fast_live_bytes=0
        self.pending_deletes=OrderedDict()

    def _sample(self):
        resources.spill_sample.update(memory_bytes=self.memory_bytes,disk_bytes=self.disk_bytes,
            written_bytes=self.written_bytes,limit_bytes=self.limit,spilled_arrays=len(self.slow),
            ssd_live_bytes=self.fast_live_bytes,ssd_limit_bytes=self.fast_limit,
            ssd_directory=str(self.fast_folder) if self.fast_folder else None)

    def _remove(self,path,size):
        try: path.unlink()
        except FileNotFoundError: pass
        except PermissionError: return False
        if self.fast_folder and path.parent==self.fast_folder: self.fast_live_bytes-=size
        return True

    def _retry_deletes(self):
        for path in list(islice(self.pending_deletes,64)):
            size=self.pending_deletes[path]
            if self._remove(path,size): del self.pending_deletes[path]
            else: self.pending_deletes.move_to_end(path)

    def __getitem__(self, key):
        if key in self.fast:
            self.fast.move_to_end(key)
            return self.fast[key]
        path,_=self.slow[key]
        return np.load(path,allow_pickle=False,mmap_mode='c')

    def __setitem__(self,key,value):
        if key in self: del self[key]
        weight=value.nbytes if type(value) in (np.ndarray,np.memmap) and not value.dtype.hasobject else 0
        self.fast[key]=value; self.weights[key]=weight; self.memory_bytes+=weight
        while self.memory_bytes>self.limit:
            victim=next(k for k in self.fast if self.weights[k])
            array=self.fast[victim]; size=self.weights[victim]
            if self.sequence%128==0: self._retry_deletes()
            chosen=self.folder
            if (self.fast_folder and self.fast_live_bytes+size+4096<=self.fast_limit
                    and shutil.disk_usage(self.fast_folder).free-size-4096>=self.fast_reserve):
                chosen=self.fast_folder
            if self.budget and chosen==self.folder: self.budget(size+4096)
            path=chosen/f'array_{self.sequence:09d}.npy'; self.sequence+=1
            # np.save writes the original dtype/values, including NaN payloads.
            with path.open('wb') as stream: np.save(stream,array,allow_pickle=False)
            file_size=path.stat().st_size
            if chosen==self.fast_folder: self.fast_live_bytes+=file_size
            self.slow[victim]=(path,file_size); self.disk_bytes+=file_size; self.written_bytes+=file_size
            del self.fast[victim]; self.memory_bytes-=self.weights.pop(victim)
        self._sample()

    def __delitem__(self,key):
        if key in self.fast:
            del self.fast[key]; self.memory_bytes-=self.weights.pop(key)
        else:
            path,size=self.slow.pop(key)
            # Mapped reads may still be referenced by running tasks on Windows;
            # unlink later when the private cache directory is closed.
            if not self._remove(path,size): self.pending_deletes[path]=size
            self.disk_bytes-=size
        self._sample()

    def __contains__(self,key): return key in self.fast or key in self.slow
    def __iter__(self): return iter((*self.fast,*self.slow))
    def __len__(self): return len(self.fast)+len(self.slow)


@contextmanager
def bounded_compute(root,limit=2*1024**3,workers=None):
    root=Path(root).resolve(); scratch=(root/'scratch').resolve(); scratch.mkdir(exist_ok=True)
    # Only this newly created private scratch directory may be recursively cleaned.
    temporary=TemporaryDirectory(prefix='dask_spill_',dir=scratch,ignore_cleanup_errors=True)
    folder=Path(temporary.name).resolve()
    if not folder.is_relative_to(scratch): raise ValueError('Spill cache outside project scratch')
    commit=resources.commit_usage()
    if commit:
        limit=min(limit,max(128*1024**2,(commit['available_bytes']-2*1024**3)//3))
    default_workers=1 if commit and commit['available_bytes']<6*1024**3 else 2
    cache=ArraySpillCache(folder,limit,budget=lambda size:check_disk(root,size))
    fast_temporary=None
    configuration=root/'project.json'
    settings=json.loads(configuration.read_text(encoding='utf-8')) if configuration.exists() else {}
    requested_workers=workers if workers is not None else settings.get('compute_workers',default_workers)
    # Opt-in only. Existing jobs keep the qualified conservative default.
    if isinstance(requested_workers,bool) or not isinstance(requested_workers,int) or not 1<=requested_workers<=8:
        raise ValueError('compute_workers must be an integer from1 through8')
    physical=resources.psutil.virtual_memory().available
    ram_slots=max(1,(physical-resources.RAM_RESERVE)//(512*1024**2))
    commit_slots=max(1,(commit['available_bytes']-2*1024**3)//(512*1024**2)) if commit else 8
    workers=max(1,min(requested_workers,ram_slots,commit_slots))
    resources.spill_sample.update(requested_workers=requested_workers,admitted_workers=workers)
    requested=settings.get('fast_scratch_directory')
    if requested:
        fast_root=Path(requested).resolve()
        if any(fast_root.is_relative_to(root/name) for name in ('raw','exports')):
            raise ValueError('SSD temporary files must be separate from raw/permanent exports')
        fast_root.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(fast_root).free>=32*1024**3+1024**3:
            fast_temporary=TemporaryDirectory(prefix='dask_spill_',dir=fast_root,ignore_cleanup_errors=True)
            fast_folder=Path(fast_temporary.name).resolve()
            if not fast_folder.is_relative_to(fast_root): raise ValueError('SSD spill outside private scratch root')
            cache.fast_folder=fast_folder
    try:
        # Local scheduler accepts a dict-like task cache directly. No process
        # boundary or graph serialization can copy full native memory maps.
        with dask.config.set(cache=cache,scheduler='threads',num_workers=workers):
            yield cache
    finally:
        cache.fast.clear(); cache.slow.clear(); cache.weights.clear()
        import gc
        gc.collect()
        temporary.cleanup()
        if fast_temporary: fast_temporary.cleanup()
