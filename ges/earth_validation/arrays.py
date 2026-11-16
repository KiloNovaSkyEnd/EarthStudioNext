"""Expose bounded array windows without eager full-array copying or hashing."""


class ReadOnlyArray:
    def __init__(self,values):
        self.values=values; self.shape=values.shape; self.dtype=values.dtype; self.ndim=values.ndim
    def __getitem__(self,index): return self.values[index]
