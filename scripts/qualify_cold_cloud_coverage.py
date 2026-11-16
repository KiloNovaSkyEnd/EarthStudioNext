"""Compare repaired cold-cloud output with actual unmodified Satpy compositors."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges.earth_validation import bootstrap  # noqa: F401
import argparse
import json
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.windows import Window
import xarray as xr
from satpy.composites.mask import LowCloudCompositor, HighCloudCompositor
from ges.earth_validation import stock
from ges.earth_validation.satpy_execution import BoundedLowCloudCompositor, BoundedHighCloudCompositor
from ges.earth_validation.spill import bounded_compute
from ges.earth_validation.project import save


def main(root):
    root=Path(root); reference=stock.configure(root)
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    descriptor=next(s for s in plan['scenes'] if s['sensor']=='himawari8' and s['nominal_utc']==plan['frames'][0])
    scene,_=stock.open_scene(root,plan,descriptor)
    area=scene['B03'].attrs['area']; target=area[slice(5244,6268),slice(8188,9212)]
    paths=[]
    for name in ('stock_reference','repaired'):
        with patch.object(BoundedLowCloudCompositor,'__call__',
                          LowCloudCompositor.__call__ if name=='stock_reference' else BoundedLowCloudCompositor.__call__), \
                patch.object(BoundedHighCloudCompositor,'__call__',
                          HighCloudCompositor.__call__ if name=='stock_reference' else BoundedHighCloudCompositor.__call__):
            if name=='stock_reference':
                # Diagnostic only: no extra post-composite footprint veto. This
                # crop has all primary visible/thermal-window observations.
                with patch.object(stock,'observed_support',lambda s,n:xr.full_like(s[n[0]],True,dtype=bool)):
                    result,grid=stock.compose(scene,target,root/'raw/references/blackmarble_2016_500m/global_500m.vrt',
                        reference,native=True,native_tile=True,night_cache=root/'processed/static_night_grids_v1')
            else:
                result,grid=stock.compose(scene,target,root/'raw/references/blackmarble_2016_500m/global_500m.vrt',
                    reference,native=True,native_tile=True,night_cache=root/'processed/static_night_grids_v1')
            path=root/f'reports/cold_cloud_{name}_v21.tif'
            with bounded_compute(root):
                result.save_dataset('geo_color',filename=str(path),writer='geotiff',dtype=np.uint8,
                                    tiled=True,compress='DEFLATE',include_scale_offset_tags=False)
            paths.append(path)
    with rasterio.open(paths[0]) as expected,rasterio.open(paths[1]) as repaired, \
            rasterio.open(root/'processed/stock_geocolor'/descriptor['scene_id']/'full_native_disk_v3/geo_color.tif') as previous:
        new=repaired.read(); reference_pixels=expected.read()
        assert expected.transform==repaired.transform and expected.crs==repaired.crs
        assert np.array_equal(new,reference_pixels),'Repaired crop differs from stock recipe'
        col,row=~previous.transform*(repaired.bounds.left,repaired.bounds.top)
        old=previous.read(window=Window(round(col),round(row),repaired.width,repaired.height))
        holes=old[3]==0
        assert np.any(holes) and np.all(new[3][holes]==255)
        assert np.array_equal(old[:,~holes],new[:,~holes]),'Previously valid pixels changed'
        record={'scene_id':descriptor['scene_id'],'shape':list(repaired.shape),'stock_rgba_and_georeferencing_identical':True,
            'old_false_holes':int(holes.sum()),'restored_stock_observed_pixels':int(holes.sum()),
            'previous_valid_rgba_identical':True,'repaired_alpha_missing':int((new[3]==0).sum()),
            'global_delivery_complete':False,'limits':'Actual cold-cloud regional qualification; new complete sensor products still required.'}
    save(root/'reports/cold_cloud_coverage_qualification_v21.json',record)
    print(json.dumps(record),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
    main(parser.parse_args().root)
