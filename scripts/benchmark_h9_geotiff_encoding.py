"""Actual full native tile lossless compression/threads test, no science rerun."""
from pathlib import Path
import json,time
import numpy as np
import rasterio

root=Path(__file__).resolve().parents[1]
project=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
out=project/'reports/geotiff_encoding_benchmark'
out.mkdir(exist_ok=False)
source=project/'processed/20261020T1410Z/native_05500_05500.tif'
with rasterio.open(source) as src:
    pixels=src.read();profile=src.profile.copy();transform=src.transform;crs=src.crs
records=[]
for label,level,threads in [('baseline',6,1),('threaded',6,4),('fast_lossless',1,4),('baseline_repeat',6,1)]:
    target=out/(label+'.tif');options={**profile,'compress':'deflate','predictor':2,'zlevel':level,'num_threads':threads}
    began=time.monotonic()
    with rasterio.open(target,'w',**options) as dst:dst.write(pixels)
    elapsed=time.monotonic()-began
    with rasterio.open(target) as actual:
        identical=np.array_equal(actual.read(),pixels) and actual.transform==transform and actual.crs==crs
    if not identical:raise ValueError('Lossless encoding changed pixels/georeferencing')
    records.append(dict(label=label,zlevel=level,gdal_threads=threads,seconds=elapsed,bytes=target.stat().st_size,
        identical_rgba_and_georeferencing=identical))
    (out/'results.json').write_text(json.dumps(dict(source=str(source),shape=list(pixels.shape),records=records),indent=2))
    print('GEOTIFF_ENCODING',json.dumps(records[-1]),flush=True)
