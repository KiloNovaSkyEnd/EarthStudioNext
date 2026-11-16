"""Real observed overlap parity and end-to-end CUDA transfer timing."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject,Resampling
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges.earth_validation.fusion import fuse
from ges.earth_validation.gpu import device

parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
args=parser.parse_args(); root=Path(args.root)
bounds=(-130,-10,-90,30); size=1282; transform=from_bounds(*bounds,size,size)
lon,lat=np.meshgrid(bounds[0]+(np.arange(size)+.5)*40/size,bounds[3]-(np.arange(size)+.5)*40/size)
sources=[]; files=[]
for sensor in ('goes16','goes17'):
    path=root/f'processed/stock_geocolor/{sensor}_20220831T1940Z/camera_disk_2km_v1/geo_color.tif'
    pixels=np.zeros((4,size,size),np.uint8)
    with rasterio.open(path) as src:
        for band in range(1,5):
            reproject(rasterio.band(src,band),pixels[band-1],src_transform=src.transform,
                      src_crs=src.crs,dst_transform=transform,dst_crs='EPSG:4326',resampling=Resampling.nearest)
        sources.append((pixels.transpose(1,2,0),src.crs.to_dict()['lon_0']))
    files.append(str(path))
timings={}; outputs={}
for backend in ('cpu','cuda'):
    fuse(sources,lon,lat,backend=backend)  # Warm-up includes CUDA compilation.
    elapsed=[]
    for _ in range(5):
        start=perf_counter(); outputs[backend]=fuse(sources,lon,lat,backend=backend)
        elapsed.append(perf_counter()-start)
    timings[backend]=float(np.median(elapsed))
cpu,gpu=outputs['cpu'],outputs['cuda']
error=np.abs(cpu[0].astype(int)-gpu[0].astype(int))
report={**device(),'real_observation_inputs':files,'shape':[size,size],
        'cpu_median_seconds':timings['cpu'],'cuda_median_seconds':timings['cuda'],
        'speedup':timings['cpu']/timings['cuda'],
        'max_rgba_error_8bit':int(error.max()),'different_values':int(np.count_nonzero(error)),
        'ownership_identical':bool(np.array_equal(cpu[1],gpu[1])),
        'alpha_identical':bool(np.array_equal(cpu[0][...,3],gpu[0][...,3])),
        'overlap_blended_pixels':int(np.count_nonzero(cpu[2])),
        'max_weight_error':float(np.max(np.abs(cpu[2]-gpu[2])))}
assert report['ownership_identical'] and report['alpha_identical']
assert report['overlap_blended_pixels']>0 and report['max_rgba_error_8bit']<=1
(root/'reports/gpu_fusion_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
