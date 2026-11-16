"""Read existing rendered GeoTIFFs for bounded weather-playback validation only.

No new low-resolution global sequence, source processing or source writes.
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
    import rasterio
    from rasterio.warp import reproject,Resampling
    from rasterio.transform import from_bounds
    from PIL import Image
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path);p.add_argument('sources',nargs='+',type=Path)
    p.add_argument('--bounds',type=float,nargs=4,required=True)
    p.add_argument('--width',type=int,default=512)
    args=p.parse_args();out=require_writable(args.output)
    if not 16<=args.width<=2048:raise ValueError('Bounded playback verification width only')
    w,s,e,n=args.bounds
    if not -180<=w<e<=180 or not -90<=s<n<=90:raise ValueError('Invalid bounds')
    height=round(args.width*(n-s)/(e-w))
    if not 1<=height<=2048:raise ValueError('Invalid sample height')
    if (out/'manifest.json').exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True,exist_ok=True);frames=[]
    for i,folder in enumerate(args.sources):
        source=folder/'geo_color.tif';meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
        if not meta.get('stock_recipes_and_enhancements'):raise ValueError('Only existing stock Satpy products accepted')
        result=np.zeros((4,height,args.width),dtype=np.uint8)
        with rasterio.open(source) as src:
            if src.count!=4 or set(src.dtypes)!={'uint8'}:raise ValueError('RGBA uint8 display input required')
            for band in range(1,5):
                reproject(rasterio.band(src,band),result[band-1],src_transform=src.transform,src_crs=src.crs,
                    dst_transform=from_bounds(w,s,e,n,args.width,height),dst_crs='EPSG:4326',resampling=Resampling.nearest)
            source_resolution=abs(src.transform.a)
        filename=f'frame_{i:03}.png';Image.fromarray(result.transpose(1,2,0)).save(out/filename)
        frames.append({'utc':meta['nominal_utc'],'source':meta['sensor']+' / Satpy '+meta['satpy_version'],
            'recipe':meta['profile'],'detail':'bounded-sample','kind':'single-image','bounds':args.bounds,'path':filename,
            'sourcePath':str(source.resolve()),'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'sourceGridMetres':source_resolution,'sourceBands':meta['source_bands'],
            'limits':f'EXISTING {source_resolution:g}m display source, weather-playback wiring test ONLY; not native-detail delivery; no weather interpolation or generated frames.'})
    frames.sort(key=lambda f:f['utc'])
    if len({x['utc'] for x in frames})!=len(frames):raise ValueError('Duplicate scan')
    (out/'manifest.json').write_text(json.dumps({'schema':'earthstudio.materials.v1','earthModel':'WGS84','scope':'regional','frames':frames},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'frames':len(frames),'width':args.width,'height':height,'native_detail_verified':False}))


if __name__=='__main__':main()
