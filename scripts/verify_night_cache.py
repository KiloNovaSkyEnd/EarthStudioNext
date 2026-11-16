"""Real full sensor-grid static-background parity and materialized read timings."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
import numpy as np
from pyresample.geometry import AreaDefinition
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges.earth_validation.night_background import read_on_area

parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
args=parser.parse_args(); root=Path(args.root)
metadata=root/'processed/stock_geocolor/himawari8_20220901T0500Z/camera_disk_2km_v1/metadata.json'
if not metadata.exists(): metadata=root/'processed/quality_before_night_navigation_v2/himawari8_20220901T0500Z/camera_disk_2km_v1/metadata.json'
record=json.loads(metadata.read_text(encoding='utf-8'))
height,width=record['shape']
area=AreaDefinition('benchmark','','',record['crs_wkt'],width,height,record['extent'])
source=root/'raw/references/blackmarble_2016_500m/global_500m.vrt'
start=perf_counter(); original=read_on_area(source,area); original_seconds=perf_counter()-start
start=perf_counter(); first=read_on_area(source,area,root/'processed/static_night_grids_v1'); first_seconds=perf_counter()-start
assert np.array_equal(original,first,equal_nan=True)
del first
elapsed=[]
for _ in range(3):
    start=perf_counter(); cached=np.array(read_on_area(source,area,root/'processed/static_night_grids_v1'),copy=True)
    elapsed.append(perf_counter()-start)
    assert np.array_equal(original,cached,equal_nan=True)
report={'shape':list(original.shape),'dtype':str(original.dtype),'uncached_warp_seconds':original_seconds,
        'cache_creation_seconds':first_seconds,'cached_materialized_seconds':elapsed,
        'speedup_static_night_only':original_seconds/float(np.median(elapsed)),
        'all_values_and_nan_mask_identical':True,'pixel_colour_algorithm_changed':False}
report['nonzero_values']=int(np.count_nonzero(np.nan_to_num(original)))
assert report['nonzero_values']>0,'Full-disk background must contain genuine night reference pixels'
import rasterio
from pyproj import Transformer
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from rasterio.transform import from_bounds
x,y=area.get_proj_vectors(); navigation=Transformer.from_crs(area.crs,'EPSG:4326',always_xy=True)
controls=[]
with rasterio.open(source) as src:
    for row in np.linspace(400,height-401,9,dtype=int):
        for col in np.linspace(400,width-401,9,dtype=int):
            lon,lat=navigation.transform(x[col],y[row])
            if not np.isfinite(lon) or not np.isfinite(lat): continue
            expected=next(src.sample([(lon,lat)]))
            controls.append(bool(np.array_equal(expected,original[:,row,col])))
    with WarpedVRT(src,crs=area.crs,transform=from_bounds(*area.area_extent,width,height),width=width,height=height,
            resampling=rasterio.enums.Resampling.nearest,tolerance=1e-9,dtype='float32',nodata=np.nan,warp_mem_limit=64) as warped:
        patches=[]
        for row,col in [(1200,2700),(2000,2000),(3200,3300)]:
            reference=warped.read([1,2,3],window=Window(col,row,32,32))
            patches.append(bool(np.array_equal(reference,original[:,row:row+32,col:col+32],equal_nan=True)))
report['real_source_control_points']=len(controls)
report['all_source_controls_equal']=bool(controls and all(controls))
report['gdal_small_window_patches_equal']=patches
assert report['all_source_controls_equal'] and all(patches)
(root/'reports/night_cache_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
