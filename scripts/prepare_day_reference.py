"""Budget-checked NASA static cloud-free ground reference, never cloud data."""
from pathlib import Path
import hashlib,json,os
import requests
from PIL import Image
from ges.storage import load_config,preflight

URL='https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/bmng-topography/october/world.topo.200410.3x5400x2700.jpg'


def main():
    cfg=load_config();p=cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg'
    if p.exists() and p.with_suffix('.json').exists():
        m=json.loads(p.with_suffix('.json').read_text())
        if p.stat().st_size==m['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==m['sha256']:return
        raise ValueError('Existing reference differs; do not overwrite raw data')
    with requests.get(URL,stream=True,timeout=90) as r:
        r.raise_for_status();size=int(r.headers.get('content-length',0))
        if size<=0:raise ValueError('Official reference byte size unavailable')
        preflight(size,p.parent,cfg);p.parent.mkdir(parents=True,exist_ok=True)
        tmp=p.with_suffix('.partial');count=0;digest=hashlib.sha256()
        with tmp.open('wb') as f:
            for part in r.iter_content(1024*1024):
                count+=len(part)
                if count>size:raise ValueError('Reference exceeds declared byte size')
                f.write(part);digest.update(part)
        if count!=size:raise ValueError('Reference byte size mismatch')
        with Image.open(tmp) as im:
            if im.size!=(5400,2700):raise ValueError('Unexpected reference dimensions')
            im.verify()
        os.replace(tmp,p)
    p.with_suffix('.json').write_text(json.dumps({'kind':'static cloud-free ground reference, NOT 2020 observations or cloud coverage',
        'source_url':URL,'documentation':'https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography/',
        'reference_month':'2004-10','width':5400,'height':2700,'native_ground_km':8,
        'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'bytes':size,'sha256':digest.hexdigest(),
        'credit':'NASA Earth Observatory Blue Marble Next Generation'},indent=2),encoding='utf-8')
    print('STATIC GROUND VERIFIED',size,flush=True)


if __name__=='__main__':main()
