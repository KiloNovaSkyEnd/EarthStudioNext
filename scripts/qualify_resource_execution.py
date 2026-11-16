"""Bounded real-observation parity and unchanged low-cloud planning benchmark."""
import argparse
import json
from pathlib import Path
from time import perf_counter
import numpy as np
import dask.array as da
import xarray as xr
import rasterio
from pyproj import Transformer
from satpy.composites.mask import LowCloudCompositor
from ges.earth_validation.satpy_execution import BoundedLowCloudCompositor
from ges.earth_validation.stock import configure,open_scene,export_scene
from ges.earth_validation.project import save


def main(root):
    root=Path(root)
    previous=json.loads((root/'reports/engine_runtime.json').read_text(encoding='utf-8'))
    baseline=Path(previous['native_stock_composite']).parent/'geo_color.tif'
    timings=[]
    for size in (512,2048):
        y,x=da.indices((size,size),chunks=(128,128),dtype='float32')
        inputs=[xr.DataArray(v,dims=('y','x')) for v in
                ((x+y)%8, 228+(x%5), da.where(x%3==0,100.,0.))]
        outputs=[]
        for cls in (LowCloudCompositor,BoundedLowCloudCompositor):
            began=perf_counter(); result=cls('low',values_land=100)(inputs)
            seconds=perf_counter()-began
            outputs.append(result)
            timings.append({'size':size,'implementation':cls.__name__,'planning_seconds':seconds,
                            'graph_layers':len(result.data.dask.layers)})
        # Actual computation on the small comparison, full values and NaNs.
        if size==512: xr.testing.assert_identical(outputs[0].compute(),outputs[1].compute())
    configure(root)
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    descriptor=next(s for s in reversed(plan['scenes']) if s['sensor']=='himawari8')
    scene,records=open_scene(root,plan,descriptor); area=scene['B03'].attrs['area']
    x,y=Transformer.from_crs('EPSG:4326',area.crs,always_xy=True).transform(127,25)
    col=int((x-area.area_extent[0])/area.pixel_size_x)//4*4
    row=int((area.area_extent[3]-y)/area.pixel_size_y)//4*4
    crop=area[slice(row-32,row+32),slice(col-32,col+32)]
    began=perf_counter()
    output=export_scene(root,plan,descriptor,crop,'resource_qualification_v15',
        root/'raw/references/blackmarble_2016_500m/global_500m.vrt',native=True,opened=(scene,records))
    with rasterio.open(baseline) as old,rasterio.open(Path(output).parent/'geo_color.tif') as new:
        identical=(old.crs==new.crs and old.transform==new.transform and
                   np.array_equal(old.read(),new.read(),equal_nan=True))
    if not identical: raise ValueError('Real native RGBA or navigation changed')
    report={'low_cloud_planning':timings,'real_native_rgba_and_georeferencing_identical':identical,
            'baseline':str(baseline),'optimized':str(output),'real_export_seconds':perf_counter()-began,
            'limits':'Planning microbenchmark and regional observation only; not full-global speed or visual acceptance.'}
    save(root/'reports/resource_execution_qualification.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
    main(parser.parse_args().root)
