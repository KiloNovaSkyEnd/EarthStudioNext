"""Full-grid still from committed layers; the editable layers remain independent.

This convenient flattened JPG includes default ground contribution, but does not
bake Blender atmosphere/airglow. It is explicitly a recomposition of JPEG layers.
"""
import json
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
from ges_next.production.assets import verify_assets, record, write_json
from ges_next.production.jpeg_layers import reconstruct


def export_still(root, quality=None, report=lambda value:None):
    import rasterio
    from rasterio.windows import Window
    from rasterio.enums import Resampling
    root=Path(root)
    manifest=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'))
    if len(manifest['nodes'])!=1 or manifest['nodes'][0]['missing']:
        raise ValueError('单帧图片需要一个真实观测时次')
    verify_assets(root,manifest['files']+manifest['auxiliary_files'])
    source=json.loads((root/'provenance/0001/commit.json').read_text(encoding='utf-8'))
    quality=quality if quality is not None else source['assets'][0].get('quality',95)
    if type(quality) is not int or not 1<=quality<=100:raise ValueError('JPEG质量应为1..100')
    height,width=manifest['native_shape']
    target=root/'GeoColor.jpg'
    if target.exists():raise FileExistsError('已有单帧图片保留，请选择新交付目录')
    report(dict(phase='exporting-full-grid-still',shape=[height,width]))
    # Bounded array arithmetic: 256 rows, with encoded RGB accumulated on disk.
    with tempfile.TemporaryFile(dir=root) as scratch:
        scratch.truncate(height*width*3)
        pixels=np.memmap(scratch,dtype=np.uint8,mode='r+',shape=(height,width,3))
        try:
            from contextlib import ExitStack
            with ExitStack() as stack:
                readers=[stack.enter_context(rasterio.open(root/f'assets/{role}/weather_0001.{ext}'))
                         for role,ext in [('base','jpg'),('night','jpg'),('transmission','png'),('support','png')]]
                for top in range(0,height,256):
                    bottom=min(height,top+256);window=Window(0,top,width,bottom-top)
                    base=readers[0].read(window=window).transpose(1,2,0)
                    scale=readers[1].width/width
                    night=readers[1].read(window=Window(0,top*scale,width*scale,(bottom-top)*scale),
                        out_shape=(3,bottom-top,width),resampling=Resampling.average).transpose(1,2,0)
                    transmission=readers[2].read(1,window=window);support=readers[3].read(1,window=window)
                    rgb=np.rint(reconstruct(base,night,transmission)*255).astype(np.uint8)
                    rgb[support==0]=0;pixels[top:bottom]=rgb
            pixels.flush()
            Image.fromarray(pixels).save(target,format='JPEG',quality=quality,subsampling=0)
        finally:
            pixels._mmap.close()
    with Image.open(target) as image:
        image.load()
        if image.size!=(width,height):raise ValueError('单帧图片尺寸不符')
    result=dict(schema='earthstudio.still_delivery.v1',utc=manifest['nodes'][0]['utc'],
                image=record(root,target,'flattened-default-geocolor',[height,width]),jpeg_quality=quality,
                layers_remain_editable=True,atmosphere_in_blender=True,
                independent_night_shape=next(a['shape'] for a in manifest['files'] if a['role']=='shared-static-night-background'),
                note='Flat still uses cloud grid; finer independent ground layer retained forBlender. Recomposed from committed JPEG layers; additional JPEG encoding is lossy. Outside observation support is black.')
    write_json(root/'still_delivery.json',result)
    report(dict(phase='still-ready',path=str(target),utc=result['utc']))
    return result
