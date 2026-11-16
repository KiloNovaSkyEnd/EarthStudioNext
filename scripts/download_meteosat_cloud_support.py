"""Budgeted atomic download of catalog-listed CLM/CTH GRIB entries, no secrets in logs."""
import hashlib,json
from pathlib import Path
from urllib.parse import urlsplit
import requests
from ges.eumetsat_auth import authenticated_token
from ges.storage import load_config,preflight
from ges.catalog import utc_time


def main():
    cfg=load_config();folder=Path('data/processed/validation_v5')
    inventories=json.loads((folder/'meteosat_cth_inventory.json').read_text())
    inventories+=json.loads(Path('data/processed/cloud_evidence_inventory/eumetsat_20201029T164000Z.json').read_text())
    selected=[]
    for collection in ['CTH','CTH-IODC','CLM','CLM-IODC']:
        row=next(r for r in inventories if r['collection']=='EO:EUM:DAT:MSG:'+collection)
        features=row['response']['features']
        feature=next(f for f in features if f['properties']['date'].startswith('2020-10-29T16:30:00Z'))
        p=feature['properties'];entry=next(e for e in p['links']['sip-entries'] if e['title'].endswith('.grb'))
        if urlsplit(entry['href']).hostname!='api.eumetsat.int' or Path(entry['title']).name!=entry['title']:
            raise ValueError('Unexpected cloud-support URL or filename')
        selected.append({'collection':row['collection'],'product_id':p['identifier'],'date':p['date'],
                         'url':entry['href'],'filename':entry['title']})
    token=authenticated_token()
    for s in selected:
        with requests.get(s['url'],auth=token.auth,headers={'Range':'bytes=0-0','Accept-Encoding':'identity'},stream=True,timeout=45) as r:
            if r.status_code!=206:raise RuntimeError('Cloud support range HTTP '+str(r.status_code))
            s['bytes']=int(r.headers['Content-Range'].split('/')[-1])
    print('PREFLIGHT',preflight(sum(s['bytes'] for s in selected),cfg.raw_dir,cfg),flush=True)
    for platform in ['MSG4','MSG1']:
        files=[s for s in selected if s['filename'].startswith(platform+'-')]
        root=cfg.raw_dir/f'meteosat_{platform.lower()}_cloud_l2_20201029T163000Z';root.mkdir(parents=True,exist_ok=True)
        for s in files:
            target=root/s['filename'];partial=target.with_suffix('.grb.part')
            if not (target.exists() and target.stat().st_size==s['bytes']):
                count=0
                try:
                    with requests.get(s['url'],auth=token.auth,headers={'Accept-Encoding':'identity'},stream=True,timeout=(30,90)) as r:
                        if r.status_code!=200:raise RuntimeError('Cloud support full HTTP '+str(r.status_code))
                        with partial.open('wb') as f:
                            for chunk in r.iter_content(1024*1024):
                                count+=len(chunk)
                                if count>s['bytes']:raise ValueError('Cloud support exceeds verified budget')
                                f.write(chunk)
                    if count!=s['bytes']:raise ValueError('Incomplete cloud support stream')
                    partial.replace(target)
                finally:partial.unlink(missing_ok=True)
            s['sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
        manifest={'satellite':'meteosat_'+platform.lower()+'_cloud_l2','product':'SEVIRI-L2-CLM-CTH',
                  'observed_utc':'2020-10-29T16:30:00Z','local_files':[str((root/s['filename']).resolve()) for s in files],
                  'object_sizes':[s['bytes'] for s in files],'total_bytes':sum(s['bytes'] for s in files),'sources':files,
                  'reader_and_scan_alignment_verified':False}
        p=root/'scene.json';temp=p.with_suffix('.tmp');temp.write_text(json.dumps(manifest,indent=2),encoding='utf-8');temp.replace(p)
        print('CLOUD SUPPORT MANIFEST',p,flush=True)


if __name__=='__main__':
    try:main()
    except Exception as e:
        # No URL-bearing response bodies or OAuth exceptions in logs.
        print('Cloud support download failed:',type(e).__name__,flush=True)
        raise SystemExit(1)
