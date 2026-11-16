"""Real first-node night scene: unmodified stock versus equivalent execution."""
import argparse
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
import numpy as np
import rasterio
from pyproj import Transformer
from satpy.composites.mask import LowCloudCompositor
from ges.earth_validation.satpy_execution import BoundedLowCloudCompositor
from ges.earth_validation.stock import configure,open_scene,compose
from ges.earth_validation.project import save


def main(root):
    root=Path(root); reference=configure(root)
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    descriptor=next(s for s in plan['scenes'] if s['sensor']=='himawari8' and s['nominal_utc']==plan['frames'][0])
    scene,_=open_scene(root,plan,descriptor); area=scene['B03'].attrs['area']
    x,y=Transformer.from_crs('EPSG:4326',area.crs,always_xy=True).transform(127,25)
    col=int((x-area.area_extent[0])/area.pixel_size_x)//4*4
    row=int((area.area_extent[3]-y)/area.pixel_size_y)//4*4
    crop=area[slice(row-256,row+256),slice(col-256,col+256)]
    paths=[]; times=[]
    original=LowCloudCompositor.__call__; optimized=BoundedLowCloudCompositor.__call__
    for name,method in [('stock',original),('optimized',optimized)]:
        began=perf_counter()
        # This diagnostic process only; production installs no global patch.
        with patch.object(BoundedLowCloudCompositor,'__call__',method):
            result,_=compose(scene,crop,root/'raw/references/blackmarble_2016_500m/global_500m.vrt',
                reference,native=True,native_tile=True,
                night_cache=root/'processed/static_night_grids_v1')
            path=root/f'reports/resource_night_parity_v15_{name}.tif'
            result.save_dataset('geo_color',filename=str(path),writer='geotiff',dtype=np.uint8,
                compress='DEFLATE',tiled=True,include_scale_offset_tags=False)
        paths.append(path); times.append(perf_counter()-began)
    with rasterio.open(paths[0]) as old,rasterio.open(paths[1]) as new:
        identical=old.crs==new.crs and old.transform==new.transform and np.array_equal(old.read(),new.read())
        shape=list(new.shape)
    if not identical: raise ValueError('Actual night observation changed')
    report={'scene_id':descriptor['scene_id'],'nominal_utc':descriptor['nominal_utc'],
        'shape':shape,'stock_and_optimized_seconds':times,'rgba_and_georeferencing_identical':identical,
        'files':[str(p) for p in paths],'limits':'Regional first-node night test, not full-disk timing or global acceptance.'}
    save(root/'reports/resource_night_parity_v15.json',report); print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
    main(parser.parse_args().root)
