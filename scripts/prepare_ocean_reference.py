"""Small authoritative static land reference; NOT satellite cloud coverage."""
import hashlib
import json
import os
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import minimum_filter
from ges.storage import load_config, preflight


def fetch_land():
    import requests
    cfg=load_config();path=cfg.raw_dir/'reference/ne_50m_land.geojson';sidecar=path.with_suffix('.json')
    if path.exists():
        m=json.loads(sidecar.read_text())
        if path.stat().st_size!=m['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=m['sha256']:
            raise ValueError('Existing raw geographic reference fails size/hash verification')
        return path,m
    api='https://api.github.com/repos/nvkelso/natural-earth-vector/commits'
    response=requests.get(api,params={'path':'geojson/ne_50m_land.geojson','per_page':1},timeout=30);response.raise_for_status()
    commit=response.json()[0]['sha']
    url=f'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{commit}/geojson/ne_50m_land.geojson'
    headers={'Accept-Encoding':'identity'}
    head=requests.head(url,headers=headers,timeout=30);head.raise_for_status();size=int(head.headers['Content-Length'])
    if not 0<size<5_000_000:raise ValueError('Unexpected static geographic reference size')
    preflight(size,path,cfg);path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_suffix('.geojson.part')
    try:
        with requests.get(url,headers=headers,stream=True,timeout=30) as r:
            r.raise_for_status();count=0
            with partial.open('xb') as f:
                for block in r.iter_content(65536):
                    count+=len(block)
                    if count>size:raise ValueError('Static reference exceeded budgeted HEAD size')
                    f.write(block)
        if count!=size:raise ValueError('Static reference byte count mismatch')
        data=json.loads(partial.read_text())
        if data['type']!='FeatureCollection':raise ValueError('Expected geographic land FeatureCollection')
        os.replace(partial,path)
    finally:
        partial.unlink(missing_ok=True)
    metadata={'kind':'static cartographic land reference, not cloud or current water observations',
              'source_url':url,'commit':commit,'bytes':size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
              'documentation':'https://www.naturalearthdata.com/downloads/50m-physical-vectors/50m-land/',
              'credit':'Natural Earth public domain 1:50m land polygons',
              'limitations':'Cartographic coastline, no tide/sea-ice or contemporaneous water state; not 50m pixel resolution.'}
    sidecar.write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    return path,metadata


def ocean_mask(path,width):
    """Static land complement with conservative two-pixel coastal exclusion."""
    data=json.loads(path.read_text());land=Image.new('L',(width,width//2),0);draw=ImageDraw.Draw(land)
    for feature in data['features']:
        g=feature['geometry']
        if g['type'] not in ['Polygon','MultiPolygon']:raise ValueError('Unexpected land geometry')
        polygons=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
        for polygon in polygons:
            for i,ring in enumerate(polygon):
                points=[((float(x)+180)*width/360,(90-float(y))*width/360) for x,y,*_ in ring]
                draw.polygon(points,fill=255 if i==0 else 0)
    water=255-np.asarray(land)
    # Suppress uncertain coastal material pixels; never classify by blue RGB.
    return minimum_filter(water,size=5,mode=('nearest','wrap')).astype(np.uint8)


if __name__=='__main__':
    path,metadata=fetch_land();print(path,metadata['bytes'],metadata['sha256'])
