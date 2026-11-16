"""Bounded geographic display sample from an existing georeferenced Satpy PNG.

Does not read/download L1 or claim a new native-detail master.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable


def main():
    import numpy as np
    from PIL import Image
    from pyproj import Transformer
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path); parser.add_argument('metadata',type=Path); parser.add_argument('output',type=Path)
    parser.add_argument('--bounds',nargs=4,type=float,required=True,metavar=('WEST','SOUTH','EAST','NORTH'))
    parser.add_argument('--width',type=int,default=1024)
    args=parser.parse_args(); w,s,e,n=args.bounds
    if not (-180<=w<e<=180 and -90<=s<n<=90 and 16<=args.width<=4096):
        raise ValueError('Bounded sample requires non-crossing bounds and width 16–4096')
    output=require_writable(args.output); output.mkdir(parents=True,exist_ok=True)
    if (output/'manifest.json').exists(): raise ValueError('Sample already exists; choose a new directory')
    meta=json.loads(args.metadata.read_text(encoding='utf-8'))
    with Image.open(args.image) as image:
        rgba=np.asarray(image.convert('RGBA'))
    if list(rgba.shape[:2])!=meta['shape']: raise ValueError('Metadata/image shape mismatch')
    digest=hashlib.sha256(args.image.read_bytes()).hexdigest()
    if digest!=meta['sha256']: raise ValueError('Source hash mismatch')
    height=max(1,round(args.width*(n-s)/(e-w)))
    if height>4096: raise ValueError('Sample too tall')
    lon=np.linspace(w,e,args.width,endpoint=False)+(e-w)/args.width/2
    lat=np.linspace(n,s,height,endpoint=False)-(n-s)/height/2
    x,y=Transformer.from_crs('EPSG:4326',meta['projection'],always_xy=True).transform(*np.meshgrid(lon,lat))
    xmin,ymin,xmax,ymax=meta['extent']; rows,cols=rgba.shape[:2]
    valid=np.isfinite(x)&np.isfinite(y)&(x>=xmin)&(x<xmax)&(y>ymin)&(y<=ymax)
    ix=np.floor(np.where(valid,(x-xmin)/(xmax-xmin)*cols,0)).astype(int)
    iy=np.floor(np.where(valid,(ymax-y)/(ymax-ymin)*rows,0)).astype(int)
    result=np.zeros((height,args.width,4),dtype=np.uint8); result[valid]=rgba[iy[valid],ix[valid]]
    Image.fromarray(result).save(output/'sample.png')
    manifest={'schema':'earthstudio.materials.v1','earthModel':'WGS84','scope':'regional','frames':[{
        'utc':meta['nominal_utc'],'source':meta['reader']+' / Satpy '+meta['satpy_version'],
        'recipe':meta['composite']+' / stock enhancement','detail':'bounded-sample',
        'kind':'single-image','bounds':args.bounds,'path':'sample.png',
        'scanStartUtc':meta['start_utc'],'scanEndUtc':meta['end_utc'],
        'limits':meta['limits'],'sourcePath':str(args.image.resolve()),'sourceSha256':digest,
        'sampling':'nearest, EPSG:4326 pixel centres; display sample only'}]}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'size':[args.width,height],'native_detail_verified':False}))


if __name__=='__main__': main()
