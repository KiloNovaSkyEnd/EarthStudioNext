"""Measure DEFLATE effort on retained pixels; never recompute observations."""
import time
from pathlib import Path
import numpy as np
import rasterio


def encode_exact(source,target,level):
    if isinstance(level,bool) or not isinstance(level,int) or level not in (1,6):raise ValueError('Expected lossless DEFLATE level1 or6')
    source=Path(source);target=Path(target)
    if target.exists() or target.resolve()==source.resolve():
        raise FileExistsError('Never overwrite an existing retained source or output')
    with rasterio.open(source) as src:
        pixels=src.read();profile=src.profile.copy();colors=src.colorinterp
        tags=src.tags();band_tags=[src.tags(i) for i in src.indexes]
        scales=src.scales;offsets=src.offsets
    profile.update(compress='DEFLATE',predictor=2,zlevel=level,num_threads=4)
    began=time.perf_counter()
    with rasterio.open(target,'w',**profile) as dst:
        dst.write(pixels);dst.colorinterp=colors;dst.scales=scales;dst.offsets=offsets
        dst.update_tags(**tags)
        for i,band in enumerate(band_tags,1):dst.update_tags(i,**band)
    elapsed=time.perf_counter()-began
    with rasterio.open(source) as a,rasterio.open(target) as b:
        exact=(a.shape==b.shape and a.count==b.count and a.dtypes==b.dtypes
            and a.transform==b.transform and a.crs==b.crs and a.nodata==b.nodata
            and a.colorinterp==b.colorinterp and a.scales==b.scales and a.offsets==b.offsets
            and a.tags()==b.tags() and all(a.tags(i)==b.tags(i) for i in a.indexes)
            and np.array_equal(pixels,b.read()) and np.array_equal(a.dataset_mask(),b.dataset_mask()))
    if not exact:raise ValueError('Lossless encoding changed pixels, mask or geography')
    return dict(level=level,write_seconds=elapsed,bytes=target.stat().st_size,
        all_rgba_grid_mask_and_metadata_exact=True)
