"""Mutable sinks must never be copied into the scheduler's read-only spill cache."""
class StoreTarget:
    def __init__(self, array): self.array=array
    def __setitem__(self, index, value): self.array[index]=value
    def __dask_tokenize__(self): return ('production-mutable-sink',str(self.array.filename))
