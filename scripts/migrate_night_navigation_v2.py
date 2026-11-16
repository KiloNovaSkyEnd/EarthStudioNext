"""Preserve rejected derived caches and retain only proved-identical small grids."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.transform import from_bounds
from pyresample.geometry import AreaDefinition
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges.earth_validation.night_background import read_on_area
from ges.earth_validation.project import save

parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
args=parser.parse_args(); root=Path(args.root).resolve()
products=root/'processed/stock_geocolor'; history=root/'processed/quality_before_night_navigation_v2'
night=root/'raw/references/blackmarble_2016_500m/global_500m.vrt'
groups={}; preserved=[]; retained=[]

def preserve(source,destination):
    source=source.resolve(); destination=destination.resolve()
    if not source.is_relative_to(root/'processed') or not destination.is_relative_to(history):
        raise ValueError('Derived-cache move outside verified project paths')
    if destination.exists(): raise FileExistsError('Preserved quality history already exists')
    destination.parent.mkdir(parents=True,exist_ok=True); source.rename(destination)

for metadata in list(products.glob('*/*/metadata.json')):
    record=json.loads(metadata.read_text(encoding='utf-8'))
    if record.get('night_navigation_version')==2: continue
    h,w=record['shape']; key=json.dumps([record['shape'],record['extent'],record['crs_wkt']])
    if key not in groups:
        # Large legacy full-disk warps are rejected conservatively. Avoid
        # building a 1km replacement cache when future distant views need 2km.
        equal=False
        if h*w<5_000_000:
            area=AreaDefinition('migration','','',record['crs_wkt'],w,h,record['extent'])
            path=night
            if area.crs.is_projected and min(abs(area.pixel_size_x),abs(area.pixel_size_y))>=7000:
                path=night.parent/'night_proxy_8km.tif'
            with rasterio.open(path) as source:
                with WarpedVRT(source,crs=area.crs,transform=from_bounds(*area.area_extent,w,h),width=w,height=h,
                    resampling=rasterio.enums.Resampling.nearest,tolerance=1e-9,dtype='float32',nodata=np.nan,warp_mem_limit=64) as warped:
                    old=warped.read([1,2,3])
            corrected=read_on_area(night,area,root/'processed/static_night_grids_v1')
            equal=bool(np.array_equal(old,corrected,equal_nan=True))
        groups[key]=equal
        print('GRID_PROOF',h,w,'legacy_identical',equal,flush=True)
    relative=metadata.parent.relative_to(products)
    if groups[key]:
        backup=history/relative/'metadata.before.json'; backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists(): shutil.copy2(metadata,backup)
        record['night_navigation_version']=2
        record['legacy_night_input_proved_identical']=True
        save(metadata,record); retained.append(str(metadata))
    else:
        preserve(metadata.parent,history/relative); preserved.append(str(relative))
for name in ('global_sequence_4k','camera_cells_v1'):
    source=products/name
    if source.exists(): preserve(source,history/name)
reports_history=root/'reports/quality_before_night_navigation_v2'; reports_history.mkdir(exist_ok=True)
for name in ('stock_sequence.json','stock_sequence_partial.json','completed_sequence_receipt.json'):
    source=root/'reports'/name; destination=reports_history/name
    if source.exists():
        if destination.exists(): raise FileExistsError('Existing report history preserved')
        source.rename(destination)
result={'retained_source_outputs':len(retained),'preserved_rejected_source_outputs':len(preserved),
        'grid_groups':len(groups),'preserved_history':str(history),'raw_files_changed':False,
        'retained':retained,'rebuild':preserved,'reason':'Night navigation correction; original Satpy recipes unchanged'}
save(root/'reports/night_navigation_migration.json',result)
print(json.dumps({k:v for k,v in result.items() if k not in ('retained','rebuild')}),flush=True)
