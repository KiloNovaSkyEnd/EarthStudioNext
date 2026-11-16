"""True500m static ground texture, independently sampled from the500m mosaic.

Clouds and their transmission stay on their selected grid. The same geostationary
extent gives all layers identical normalized UV coordinates, at different sizes.
"""
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
from PIL import Image
from .assets import digest,write_json,record
from ..pipeline.locking import exclusive

ROLE='shared-static-night-background'


def layer_shape(grid,role):
    return grid.get('layer_shapes',{}).get(role,grid['shape'])


def project(source,area,output,report=lambda *a,**k:None):
    import rasterio
    from rasterio.vrt import WarpedVRT
    from rasterio.transform import from_bounds
    from rasterio.windows import Window
    from rasterio.enums import Resampling
    output=Path(output)
    if output.exists():raise FileExistsError('Existing projection scratch preserved')
    values=np.lib.format.open_memmap(output,mode='w+',dtype=np.uint8,shape=(area.height,area.width,3))
    try:
        with rasterio.open(source) as src:
            if (src.width,src.height)!=(86400,43200):raise ValueError('500m output requires actual global500m source; no upscaling1km')
            with WarpedVRT(src,crs=area.crs,transform=from_bounds(*area.area_extent,area.width,area.height),
                           width=area.width,height=area.height,resampling=Resampling.nearest,
                           tolerance=1e-9,dtype='uint8',warp_mem_limit=128) as warped:
                for row in range(0,area.height,512):
                    end=min(area.height,row+512)
                    for col in range(0,area.width,512):
                        right=min(area.width,col+512)
                        stripe=warped.read([1,2,3],window=Window(col,row,right-col,end-row))
                        values[row:end,col:right]=stripe.transpose(1,2,0)
                    report('projecting-night-500m',completed=end,total=area.height)
        values.flush()
    except Exception:
        values._mmap.close();raise
    return values


def asset(source,cloud_area,quality,report=lambda *a,**k:None,cache=None):
    from pyresample.geometry import AreaDefinition
    source=Path(source).resolve()
    import rasterio
    with rasterio.open(source) as src:
        if (src.width,src.height)!=(86400,43200):raise ValueError('500m夜景需要500m全球源，不能放大1km参考')
    area=AreaDefinition('h9-night500','H9 independent500m ground','geos',cloud_area.crs,
                        cloud_area.width*2,cloud_area.height*2,cloud_area.area_extent)
    if max(abs(area.pixel_size_x),abs(area.pixel_size_y))>501:raise ValueError('Night projection is not500m')
    cache=Path(cache) if cache else Path(__file__).resolve().parents[2]/'resources/cache/night500'
    cache.mkdir(parents=True,exist_ok=True)
    manifest=source.parent/'manifest.json'
    identity=dict(source=str(source),source_identity=digest(manifest if manifest.exists() else source),
                  extent=list(area.area_extent),shape=list(area.shape),crs=area.crs.to_wkt(),quality=quality,code=digest(__file__))
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    folder=cache/key;folder.mkdir(exist_ok=True)
    target=folder/'night.jpg';receipt=folder/'receipt.json'
    with exclusive(folder/'projection.lock'):
        if receipt.exists():
            body=json.loads(receipt.read_text(encoding='utf-8'))
            if body['identity']!=identity or digest(target)!=body['asset']['sha256']:raise ValueError('Static night cache changed')
            return target,body
        raw=folder/'projection.npy'
        pixels=project(source,area,raw,report)
        try:
            from .jpeg_layers import encode_jpeg
            item=encode_jpeg(folder,'night.jpg',pixels,quality,ROLE)
            absolute=squared=count=0
            with Image.open(target) as image:
                image.load()
                for row in range(0,area.height,128):
                    end=min(area.height,row+128)
                    delta=np.asarray(image.crop((0,row,area.width,end))).astype(np.float32)-pixels[row:end]
                    absolute+=float(np.abs(delta).sum(dtype=np.float64));squared+=float((delta*delta).sum(dtype=np.float64));count+=delta.size
            psnr=float(10*np.log10(255**2/max(squared/count,1e-20)))
            if psnr<35:raise ValueError('Native500m ground JPEG screening failed')
            body=dict(identity=identity,asset=item,nominal_metres=500,psnr_db=psnr,mae=absolute/count,
                      mapping='Exact pixel-centre nearest source navigation; no1km upscaling',reference_year=2016)
            write_json(receipt,body)
        finally:pixels._mmap.close()
        # Only this newly created projection temporary; never source tiles.
        if raw.resolve().parent!=folder.resolve():raise ValueError('Unexpected projection scratch')
        raw.unlink()
        return target,body


def copy_asset(source,output,metadata):
    from .static_night import materialize
    item={**metadata['asset'],'nominal_metres':500,'reference_year':2016}
    return materialize(source,output,'assets/night.jpg',item)
