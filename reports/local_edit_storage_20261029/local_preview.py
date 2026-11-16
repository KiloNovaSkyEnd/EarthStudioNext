"""Bounded geographic/video display derivatives; formal sequence remains unchanged."""
import json
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image
from ges_next.production.jpeg_layers import reconstruct
from ges_next.production.assets import write_json,digest

Image.MAX_IMAGE_PIXELS=500_000_000


def prepare(root,width=2048,fps=12,report=lambda value:None,create_video=False):
    if width not in (1024,2048,4096) or not 1<=fps<=60:raise ValueError('预览尺寸或帧率不受支持')
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject,Resampling
    root=Path(root);sequence=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'))
    master=json.loads((root/'native_master.json').read_text(encoding='utf-8'));frames=[]
    shape=master['shape'];side=min(width,max(shape));height=max(1,round(shape[0]*side/shape[1]));size=(side,height)
    for node in sequence['nodes']:
        i=node['index'];name=f'preview/frame_{i:04d}.png';target=root/name;target.parent.mkdir(exist_ok=True)
        pixels=np.zeros((height,side,4),np.uint8)
        if not node['missing']:
            arrays=[]
            for component,extension in (('base','jpg'),('night','jpg'),('transmission','png'),('support','png')):
                from ges_next.layered_sequence.paths import layer_path
                with Image.open(layer_path(root,sequence,component,i,preview=True)) as image:
                    arrays.append(np.asarray(image.resize(size,Image.Resampling.NEAREST)))
            pixels[:,:,:3]=np.rint(reconstruct(*arrays[:3])*255).astype(np.uint8);pixels[:,:,3]=arrays[3]
        geo=np.zeros((4,width//2,width),np.uint8)
        reproject(pixels.transpose(2,0,1),geo,src_transform=from_bounds(*master['extent'],side,height),src_crs=master['crs'],
            dst_transform=from_bounds(-180,-90,180,90,width,width//2),dst_crs='EPSG:4326',src_alpha=4,dst_alpha=4,
            resampling=Resampling.nearest,num_threads=2,warp_mem_limit=64)
        Image.fromarray(geo.transpose(1,2,0)).save(target,compress_level=2)
        frames.append(dict(utc=node['utc'],label=node['utc']+(' · 缺档' if node['missing'] else ''),missing=node['missing'],
            kind='single-image',path=name,previewPath=name,previewBounds=[-180,-90,180,90],bounds=[-180,-90,180,90],
            source='Himawari-9 / AHI',recipe=sequence.get('night_recipe',{}).get('mode','Stock GeoColor')+'; layered JPEG',detail='native-product'))
        report(dict(phase='preparing-sequence-preview',completed=i,total=len(sequence['nodes'])))
    manifest=dict(schema='earthstudio.materials.v1',earthModel='WGS84',scope='regional',frames=frames,
        defaultView=dict(targetLon=130.7,targetLat=18,heading=0,pitch=-45,rangeKm=4500,roll=0,fov=40),
        layeredSequence=True,previewDisplayOnly=True,previewGroundControlsBakedDefault=True,nativeShape=shape)
    if len(frames)>1 and create_video:
        import imageio_ffmpeg
        target=root/'timelapse.mp4'
        from ges_next.performance.policy import settings
        encoder=settings()['video_encoder']
        from ges_next.layered_sequence.video import encode
        encoder=encode(root,frames,width,fps,encoder)
        manifest['videoPreview']=dict(path=target.name,width=width,height=width//2,fps=fps,frames=len(frames),encoder=encoder,
            lastFrameTime=(len(frames)-1)/fps,bytes=target.stat().st_size,sha256=digest(target),gapPolicy='hold-last-labeled')
    write_json(root/'manifest.json',manifest)
    return manifest
