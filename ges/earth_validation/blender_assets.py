"""Navigation assets prepared outside Blender; Blender needs no Satpy install."""
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image
import rasterio
from pyproj import Transformer
from ges.catalog import utc_time
from ges.solar import sun_direction
from .project import save


def prepare(root, pilot):
    root=Path(root)
    metadata=Path(pilot['native_detail'])
    record=json.loads(metadata.read_text(encoding='utf-8'))
    folder=root/'processed/stock_geocolor/blender_assets'
    folder.mkdir(parents=True,exist_ok=True)
    with rasterio.open(metadata.parent/'geo_color.tif') as source:
        pixels=source.read()
        if source.count==3: pixels=np.concatenate((pixels,source.dataset_mask()[None]),axis=0)
        Image.fromarray(pixels.transpose(1,2,0)).save(folder/'native_detail.png')
    transform=Transformer.from_crs(record['crs_wkt'],'EPSG:4326',always_xy=True)
    left,bottom,right,top=record['extent']
    x,y=np.meshgrid(np.linspace(left,right,65),np.linspace(bottom,top,65))
    lon,lat=transform.transform(x,y)
    lon,lat=np.deg2rad(lon),np.deg2rad(lat)
    radius=6371.01
    vertices=np.stack((radius*np.cos(lat)*np.cos(lon),radius*np.cos(lat)*np.sin(lon),radius*np.sin(lat)),axis=-1)
    save(folder/'native_mesh.json',{'vertices':vertices.reshape(-1,3).tolist(),'cols':64,'rows':64,
        'nominal_utc':record['nominal_utc'],'source':str(metadata),
        'limits':'One native tile at one UTC; not global native-detail coverage'})
    frames=[]
    for frame in pilot['frames']:
        frames.append({'file':frame['file'],'nominal_utc':frame['nominal_utc'],
                       'sun':sun_direction(utc_time(frame['nominal_utc'])).tolist()})
    result={'frames':frames,'native_mesh':str(folder/'native_mesh.json'),
        'native_texture':str(folder/'native_detail.png'),'native_utc':record['nominal_utc'],
        'profile':'satpy-stock-geocolor-soft-rim-v1','full_sequence':False,'global_native_detail':False,
        'seviri_natural_color_exception':True}
    save(folder/'scene_assets.json',result)
    return folder/'scene_assets.json'


def prepare_sequence(root,engine_command,engine_cwd):
    root=Path(root)
    report=json.loads((root/'reports/stock_sequence.json').read_text(encoding='utf-8'))
    if not report['complete_sequence'] or len(report['frames'])!=73:
        raise ValueError('All 73 requested nodes must be committed first')
    frames=[{'file':frame['file'],'nominal_utc':frame['nominal_utc'],
             'sun':sun_direction(utc_time(frame['nominal_utc'])).tolist()} for frame in report['frames']]
    target=root/'processed/stock_geocolor/blender_sequence_assets/scene_assets.json'
    save(target,{'frames':frames,'profile':'satpy-stock-geocolor-soft-rim-v1',
        'full_sequence':True,'global_native_detail':False,'seviri_natural_color_exception':True,
        'engine_command':engine_command,'engine_cwd':str(engine_cwd)})
    return target
