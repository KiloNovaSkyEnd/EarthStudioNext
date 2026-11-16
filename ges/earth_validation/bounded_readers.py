"""Stock AHI decoding/calibration, with bounded reads of original HSD counts."""
import hashlib
from pathlib import Path
import dask.array as da
import numpy as np
from satpy.readers.ahi_hsd import AHIHSDFileHandler
from satpy.utils import normalize_low_res_chunks
from .arrays import ReadOnlyArray


class BoundedAHIHSDFileHandler(AHIHSDFileHandler):
    def _read_data(self,fp_,header,resolution):
        nlines=int(header['block2']['number_of_lines'].item())
        ncols=int(header['block2']['number_of_columns'].item())
        chunks=normalize_low_res_chunks(('auto','auto'),(nlines,ncols),(1100,1100),
            (int(resolution/500),int(resolution/500)),np.float32)
        offset=fp_.tell(); path=Path(self.filename); stamp=path.stat()
        values=np.memmap(path,offset=offset,dtype='<u2',shape=(nlines,ncols),mode='r')
        # Same immutable file/window is the same Dask input across modifiers;
        # identify it from metadata, without reading/hashing its entire payload.
        identity=(str(path.resolve()),stamp.st_size,stamp.st_mtime_ns,offset,(nlines,ncols),chunks)
        name='hsd-counts-'+hashlib.sha256(repr(identity).encode('utf-8')).hexdigest()
        return da.from_array(ReadOnlyArray(values),chunks=chunks,asarray=False,fancy=False,
            name=name,meta=np.empty((0,0),dtype='<u2'))
