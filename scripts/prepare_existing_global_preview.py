"""Publish already-rendered global previews without rerendering or modifying archives."""
import argparse, hashlib, json, shutil, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable

def main():
    from PIL import Image
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();out=require_writable(args.output)
    if out.exists():raise ValueError('Use a new output directory')
    records=[]
    for path in sorted(args.source.glob('weather_*.json')):
        meta=json.loads(path.read_text(encoding='utf-8'));image=path.with_suffix('.png')
        if meta['crs']!='EPSG:4326' or meta['extent']!=[-180,-90,180,90]:raise ValueError('Global geographic input required')
        with Image.open(image) as im:
            if im.mode!='RGBA' or list(reversed(im.size))!=meta['proxy_shape']:raise ValueError('Unexpected display image')
        records.append((path,image,meta))
    if not records:raise ValueError('No existing frames')
    total=sum(p.stat().st_size+i.stat().st_size for p,i,_ in records)
    if shutil.disk_usage(out.parent).free<total*2+100_000_000:raise ValueError('Insufficient free space')
    out.mkdir();frames=[]
    for path,image,meta in records:
        shutil.copy2(image,out/image.name);shutil.copy2(path,out/path.name)
        frames.append(dict(utc=meta['nominal_utc'],source='Himawari-8 / GOES-16 / GOES-17 / Meteosat-11 / Meteosat-9',
          recipe='Existing stock GeoColor + adapted SEVIRI natural day/night; geographic fusion',detail='bounded-sample',kind='single-image',bounds=meta['extent'],path=image.name,
          sourcePath=str(image.resolve()),sourceSha256=hashlib.sha256(image.read_bytes()).hexdigest(),provenance=path.name,sourceMetadata=meta,
          limits='GLOBAL PREVIEW ONLY: 4096x2048, existing 8km AHI/ABI and 12km SEVIRI grids; poles transparent. Nominal UTC; source scans differ. Not native detail or accepted complete global coverage.'))
    frames.sort(key=lambda f:f['utc'])
    manifest=dict(schema='earthstudio.materials.v1',earthModel='WGS84',scope='global-nonpolar',defaultView=dict(targetLon=127,targetLat=25,heading=0,pitch=-90,rangeKm=18000,roll=0,fov=40),frames=frames)
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(frames=len(frames),copied_bytes=total,start=frames[0]['utc'],end=frames[-1]['utc'],native_detail_verified=False)))

if __name__=='__main__':main()
