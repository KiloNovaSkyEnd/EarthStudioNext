"""Fetch published Pyspectral reference tables with budget/size/checksum checks."""
from pathlib import Path
import hashlib,json,os,tarfile
import requests
from ges.storage import load_config,preflight


def main():
    cfg=load_config();root=cfg.raw_dir/'reference/pyspectral';root.mkdir(parents=True,exist_ok=True)
    records=[]
    for record,key,sub in [(1288441,'pyspectral_atm_correction_luts_no_aerosol.tgz','rayleigh_only'),
                           (19373017,'pyspectral_rsr_data.tgz','rsr')]:
        response=requests.get(f'https://zenodo.org/api/records/{record}',timeout=60);response.raise_for_status()
        info=next(f for f in response.json()['files'] if f['key']==key)
        size=info['size'];algorithm,expected=info['checksum'].split(':');target=root/key
        preflight(size,root,cfg)
        def verified(p):
            if not p.exists() or p.stat().st_size!=size:return False
            with p.open('rb') as handle:return hashlib.file_digest(handle,algorithm).hexdigest()==expected
        if not verified(target):
            partial=target.with_suffix('.partial');digest=hashlib.new(algorithm);count=0
            with requests.get(info['links']['self'],stream=True,timeout=120) as r:
                r.raise_for_status()
                with partial.open('wb') as out:
                    for chunk in r.iter_content(1024*1024):
                        count+=len(chunk)
                        if count>size:raise ValueError('Reference download exceeds declared size')
                        out.write(chunk);digest.update(chunk)
            if count!=size or digest.hexdigest()!=expected:raise ValueError('Reference checksum/size mismatch')
            os.replace(partial,target)
        dest=root/sub;dest.mkdir(exist_ok=True)
        with tarfile.open(target) as tar:tar.extractall(dest,filter='data')
        records.append({'record':record,**info})
        print('VERIFIED',key,size,flush=True)
    (root/'references.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (root/'pyspectral.yaml').write_text('download_from_internet: false\nrayleigh_dir: '+root.as_posix()+'\nrsr_dir: '+(root/'rsr').as_posix()+'\n',encoding='utf-8')


if __name__=='__main__':main()
