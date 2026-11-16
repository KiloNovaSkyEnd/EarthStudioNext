"""Day/night actual-observation parity with forced lossless disk spilling."""
from ges.earth_validation import bootstrap  # noqa: F401
import argparse
import json
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer
from ges.earth_validation.stock import configure,open_scene,export_scene
from ges.earth_validation.project import save
from ges.earth_validation.spill import ArraySpillCache
from unittest.mock import patch


def main(root):
    root=Path(root); configure(root)
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    baselines=[json.loads((root/'reports/resource_night_parity_v15.json').read_text(encoding='utf-8'))['files'][0],
               str(Path(json.loads((root/'reports/engine_runtime.json').read_text(encoding='utf-8'))['native_stock_composite']).parent/'geo_color.tif')]
    matches=[]
    for when,baseline in zip((plan['frames'][0],plan['frames'][-1]),baselines):
        descriptor=next(s for s in plan['scenes'] if s['sensor']=='himawari8' and s['nominal_utc']==when)
        scene,records=open_scene(root,plan,descriptor); area=scene['B03'].attrs['area']
        x,y=Transformer.from_crs('EPSG:4326',area.crs,always_xy=True).transform(127,25)
        col=int((x-area.area_extent[0])/area.pixel_size_x)//4*4
        row=int((area.area_extent[3]-y)/area.pixel_size_y)//4*4
        width=256 if when==plan['frames'][0] else 32
        crop=area[slice(row-width,row+width),slice(col-width,col+width)]
        original=ArraySpillCache.__init__
        statistics={}
        def forced(self,folder,limit=2*1024**3,budget=None,**options):
            original(self,folder,limit=64*1024,budget=budget,**options)
            statistics['cache']=self
        with patch.object(ArraySpillCache,'__init__',forced):
            output=export_scene(root,plan,descriptor,crop,'spill_qualification_v16',
                root/'raw/references/blackmarble_2016_500m/global_500m.vrt',native=True,opened=(scene,records))
        with rasterio.open(baseline) as old,rasterio.open(Path(output).parent/'geo_color.tif') as new:
            identical=old.crs==new.crs and old.transform==new.transform and np.array_equal(old.read(),new.read())
            shape=list(new.shape)
        if not identical: raise ValueError('Lossless spill / smaller coordinate chunks changed real pixels')
        spilled=statistics['cache'].written_bytes
        if not spilled: raise ValueError('Qualification did not exercise disk overflow')
        matches.append({'scene_id':descriptor['scene_id'],'shape':shape,'identical':True,
                        'spilled_bytes':spilled,'metadata':str(output),'baseline':str(baseline)})
    import pyresample
    save(root/'reports/spill_execution_qualification.json',{'matches':matches,
        'pyresample_import_chunk':pyresample.CHUNK_SIZE,'no_precision_or_resolution_reduction':True,
        'limits':'Real regional pixel parity, not full native/global delivery acceptance'})
    print(json.dumps(matches),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
    main(parser.parse_args().root)
