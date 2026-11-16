"""Display-only geographic previews; retained native masters remain untouched."""
from pathlib import Path
import json,time,os

def prepare(master,width=4096):
    import numpy as np
    import rasterio
    from affine import Affine
    from rasterio.warp import reproject,Resampling
    from rasterio.transform import from_bounds
    from PIL import Image
    import xml.etree.ElementTree as ET
    from .preview_server import native_signature
    master=Path(master).resolve();signature=native_signature(master)
    target=master.parent/f'preview_{width}_{signature[:16]}.png';receipt=target.with_suffix('.json')
    if target.is_file() and receipt.is_file():return target,json.loads(receipt.read_text(encoding='utf-8'))
    started=time.perf_counter()
    with rasterio.open(master) as source:
        side=min(width,source.width)
        # Read interleaved RGBA pages together. Reading the four-band VRT can
        # decompress all16pages once per band when GDAL's block cache evicts them.
        if master.suffix.lower()=='.vrt':
            sampled=np.zeros((4,side,side),np.uint8)
            band=ET.parse(master).getroot().find('VRTRasterBand')
            for item in band.findall('SimpleSource'):
                name=item.find('SourceFilename');src=item.find('SrcRect');dst=item.find('DstRect')
                page=master.parent/name.text if name.get('relativeToVRT')=='1' else Path(name.text)
                x=round(float(dst.get('xOff'))*side/source.width);y=round(float(dst.get('yOff'))*side/source.height)
                right=round((float(dst.get('xOff'))+float(dst.get('xSize')))*side/source.width)
                bottom=round((float(dst.get('yOff'))+float(dst.get('ySize')))*side/source.height)
                window=rasterio.windows.Window(float(src.get('xOff')),float(src.get('yOff')),float(src.get('xSize')),float(src.get('ySize')))
                with rasterio.open(page) as tile:
                    sampled[:,y:bottom,x:right]=tile.read(window=window,out_shape=(4,bottom-y,right-x),resampling=Resampling.nearest)
        else:
            sampled=source.read(out_shape=(4,side,side),resampling=Resampling.nearest)
        transform=source.transform*Affine.scale(source.width/side,source.height/side)
        pixels=np.zeros((4,width//2,width),np.uint8)
        reproject(sampled,pixels,src_transform=transform,src_crs=source.crs,
                  dst_transform=from_bounds(-180,-90,180,90,width,width//2),dst_crs='EPSG:4326',
                  src_alpha=4,dst_alpha=4,resampling=Resampling.nearest,warp_mem_limit=64,num_threads=2)
    pixels[:3,pixels[3]==0]=0
    temporary=target.with_suffix('.tmp')
    Image.fromarray(pixels.transpose(1,2,0)).save(temporary,format='PNG',compress_level=2)
    os.replace(temporary,target)
    info=dict(display_only=True,width=width,height=width//2,bounds=[-180,-90,180,90],
              native_signature=signature,source=str(master),native_unchanged=True,
              sampled_geostationary_grid=side,resampling='nearest',seconds=time.perf_counter()-started,bytes=target.stat().st_size)
    receipt.write_text(json.dumps(info,indent=2),encoding='utf-8')
    return target,info

def compress_preview(png,info):
    """Small browser transfer texture; original PNG/native TIFFs are retained."""
    from PIL import Image
    png=Path(png);target=png.with_name(png.stem+'_q88.webp');receipt=target.with_suffix('.json')
    if target.is_file() and receipt.is_file():return target,json.loads(receipt.read_text(encoding='utf-8'))
    started=time.perf_counter();temporary=target.with_suffix('.tmp')
    with Image.open(png) as image:image.save(temporary,format='WEBP',quality=88,method=1)
    os.replace(temporary,target)
    metadata=dict(info,format='WEBP',display_quality=88,source_display_png=png.name,
                  bytes=target.stat().st_size,compression_seconds=time.perf_counter()-started)
    receipt.write_text(json.dumps(metadata,indent=2),encoding='utf-8');return target,metadata
