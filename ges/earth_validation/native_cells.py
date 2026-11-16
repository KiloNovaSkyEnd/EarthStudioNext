"""Global native-only weather pages. No proxy pixels, intermediate levels or fills."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject,Resampling
from rasterio.vrt import WarpedVRT
from pyresample.geometry import AreaDefinition
from .camera_tiles import cell_bounds,sensor_crop
from .fusion import fuse
from .archive import sha
from .project import save,check_disk

SIZE=1120  # Less than 500m geographic sampling; no coarser source substitutes.


def cells():
    return [(column,row) for row in range(4,32) for column in range(72)]


def write(root,metadata,column,row,index,utc,namespace='native_earth_v1'):
    if namespace not in ('native_earth_v1','native_earth_qualification_v1'): raise ValueError('Invalid native namespace')
    root=Path(root); folder=root/'processed'/namespace/'cells'/f'c{column:02d}_r{row:02d}'
    record_file=folder/f'weather_{index:04d}.json'
    if record_file.exists():
        old=json.loads(record_file.read_text(encoding='utf-8'))
        if old['nominal_utc']!=utc or sha(old['texture'])!=old['sha256']:
            raise ValueError('Committed native page changed; preserved')
        return old
    bounds=cell_bounds(column,row); west,south,east,north=bounds
    step=(east-west)/SIZE
    expanded=(west-step,south-step,east+step,north+step)
    size=SIZE+2; transform=from_bounds(*expanded,size,size)
    lon,lat=np.meshgrid(expanded[0]+(np.arange(size)+.5)*step,expanded[3]-(np.arange(size)+.5)*step)
    inputs=[]; sources=[]
    for metadata_path in metadata:
        record=json.loads(Path(metadata_path).read_text(encoding='utf-8'))
        if not record['native_grid_tile'] or record.get('night_navigation_version')!=2:
            raise ValueError('Native-only Earth refuses coarse or legacy navigation sources')
        h,w=record['shape']; area=AreaDefinition('native','','',record['crs_wkt'],w,h,record['extent'])
        if sensor_crop(area,expanded) is None: continue
        pixels=np.zeros((4,size,size),np.uint8)
        with rasterio.open(Path(metadata_path).parent/'geo_color.tif') as src:
            # Share one exact nearest navigation across all original channels.
            reproject(rasterio.band(src,list(range(1,src.count+1))),pixels[:src.count],
                src_transform=src.transform,src_crs=src.crs,dst_transform=transform,
                dst_crs='EPSG:4326',resampling=Resampling.nearest,num_threads=1,warp_mem_limit=32)
            if src.count==3:
                with WarpedVRT(src,crs='EPSG:4326',transform=transform,width=size,height=size,
                               resampling=Resampling.nearest) as view:
                    pixels[3]=view.read_masks(1)
            lon0=src.crs.to_dict()['lon_0']
        inputs.append((pixels.transpose(1,2,0),lon0)); sources.append(str(metadata_path))
    pixels,owners,_=fuse(inputs,lon,lat,backend='cuda')
    check_disk(root,pixels.nbytes*2); folder.mkdir(parents=True,exist_ok=True)
    texture=folder/f'weather_{index:04d}.png'; part=folder/f'weather_{index:04d}.part.png'
    Image.fromarray(pixels).save(part,compress_level=3); part.replace(texture)
    result={'cell':[column,row],'bounds':bounds,'texture_bounds':expanded,'size':size,'halo_pixels':1,
            'texture':str(texture),'sha256':sha(texture),'nominal_utc':utc,'sources':sources,
            'native_only':True,'proxy':False,'valid_fraction':float(np.mean(owners>0)),
            'source_resolution_note':'Native red ~500m; other actual bands ~1/2/3km. Nearest geographic sampling adds no measurements.'}
    save(record_file,result); return result
