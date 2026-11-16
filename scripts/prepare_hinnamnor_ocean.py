"""Fetch only preflighted six extra twilight scans; all legacy archives read-only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import os
from ges.storage import load_config,preflight
from ges.catalog import s3_client
from scripts.compare_hinnamnor_geocolor import sha


def main():
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_ocean_v1'
    plan=json.loads((root/'download_plan.json').read_text());assert plan['batch_ceiling_bytes']<=plan['limit_bytes']<=2_000_000_000
    preflight(plan['batch_ceiling_bytes'],cfg.raw_dir,cfg)
    client=s3_client()
    def fetch(r):
        head=client.head_object(Bucket=r['bucket'],Key=r['key'])
        assert head['ContentLength']==r['bytes'] and head['ETag']==r['etag']
        if r['kind']=='L2':return dict(r,head_verified=True,download='ROI ranges only')
        path=cfg.raw_dir/'hinnamnor_ocean_v1'/r['nominal_utc'].replace('-','').replace(':','')/Path(r['key']).name
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            part=path.with_suffix(path.suffix+'.part');assert not part.exists(),'Keep partial file; use a new version for retry'
            response=client.get_object(Bucket=r['bucket'],Key=r['key'],IfMatch=r['etag']);assert response['ContentLength']==r['bytes']
            count=0
            try:
                with part.open('xb') as f:
                    for data in response['Body'].iter_chunks(chunk_size=1024*1024):
                        count+=len(data);assert count<=r['bytes'];f.write(data)
            finally:response['Body'].close()
            assert count==r['bytes'];os.replace(part,path)
        assert path.stat().st_size==r['bytes']
        print('HSD VERIFIED',path.name,flush=True)
        return dict(r,head_verified=True,local_file=str(path.resolve()),sha256=sha(path))
    with ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(fetch,plan['files']))
    (root/'download_verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    print('PASS HSD payload',plan['hsd_bytes'],'plus bounded L2 ranges only',flush=True)


if __name__=='__main__':main()
