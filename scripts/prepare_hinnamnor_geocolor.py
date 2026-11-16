"""Fetch only the bounded three-scan GeoColor experiment, no renderer changes."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import os
import requests
from ges.catalog import s3_client
from ges.storage import load_config, preflight

REFS=[
    ('gshhs_land_water_mask_3km_i.tif', 'https://zenodo.org/records/10076199/files/gshhs_land_water_mask_3km_i.tif',
     '96df83c57416217e191f95dde3d3c1ce0373a8fc220e929228873db246ca3569'),
    ('BlackMarble_2016_3km_geo.tif', 'https://assets.science.nasa.gov/content/dam/science/esd/eo/images/imagerecords/144000/144898/BlackMarble_2016_3km_geo.tif',
     'e915ef2a20d84e2a59e1547d3ad564463ad4bcf22bfa02e0e0b8ed1cd722e9c0'),
    ('Miller2020_GeoColor.pdf','https://repository.library.noaa.gov/view/noaa/30693/noaa_30693_DS1.pdf',None)]


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--hsd-only',action='store_true');args=parser.parse_args()
    cfg=load_config();out=cfg.processed_dir/'hinnamnor_geocolor_v1'
    plan=json.loads((out/'download_plan.json').read_text())
    raw=cfg.raw_dir/'hinnamnor_geocolor_v1'
    reference=cfg.raw_dir/'reference/satpy_geocolor_v060'
    refs=[]
    for name,url,expected in REFS:
        r=requests.head(url,allow_redirects=True,timeout=50,headers={'Accept-Encoding':'identity'});r.raise_for_status()
        size=int(r.headers['Content-Length']);assert size>0
        target=reference/('composites' if name.endswith('.tif') else 'papers')/name
        refs.append({'name':name,'url':url,'final_head_url':r.url,'bytes':size,'sha256_expected':expected,'local_file':str(target.resolve())})
    total=plan['total_satellite_bytes']+sum(r['bytes'] for r in refs)
    assert sum(r['bytes'] for r in refs)<=plan['aux_cap_bytes']
    assert total<=plan['limit_bytes']
    preflight(total,raw,cfg)
    protected={str(p):[p.stat().st_size,p.stat().st_mtime_ns] for parent in [cfg.raw_dir,cfg.export_dir]
               for p in parent.rglob('*') if p.is_file() and raw not in p.parents and reference not in p.parents}
    (out/'protected_before.json').write_text(json.dumps(protected),encoding='utf-8') if not (out/'protected_before.json').exists() else None
    plan['auxiliary_files']=refs;plan['actual_planned_total_bytes']=total
    plan['note']='NASA source URL relocated; official installed SHA256 must match. Satpy configuration unchanged.'
    (out/'download_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    print('BATCH PREFLIGHT',total,'limit',plan['limit_bytes'],flush=True)
    def commit(target,expected_size,stream,expected_hash=None):
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            assert target.stat().st_size==expected_size
            digest=sha(target)
            if expected_hash:assert digest==expected_hash
            return digest
        partial=target.with_suffix(target.suffix+'.part');digest=hashlib.sha256();count=0
        with partial.open('wb') as handle:
            for block in stream:
                count+=len(block);assert count<=expected_size
                handle.write(block);digest.update(block)
        assert count==expected_size
        if expected_hash:assert digest.hexdigest()==expected_hash
        os.replace(partial,target)
        return digest.hexdigest()
    for ref in refs:
        target=Path(ref['local_file'])
        if target.exists():ref['sha256']=commit(target,ref['bytes'],[],ref['sha256_expected'])
        else:
            with requests.get(ref['url'],stream=True,timeout=120,headers={'Accept-Encoding':'identity'}) as response:
                response.raise_for_status()
                ref['sha256']=commit(target,ref['bytes'],response.iter_content(1024*1024),ref['sha256_expected'])
        print('REFERENCE VERIFIED',ref['name'],ref['bytes'],flush=True)
    client=s3_client()
    def fetch(record):
        folder=record['nominal_utc'].replace('-','').replace(':','')
        target=raw/folder/Path(record['key']).name
        if target.exists():digest=commit(target,record['bytes'],[])
        else:
            r=client.get_object(Bucket=record['bucket'],Key=record['key'],IfMatch=record['etag'])
            assert r['ContentLength']==record['bytes'] and r['ETag']==record['etag']
            try:digest=commit(target,record['bytes'],r['Body'].iter_chunks(chunk_size=1024*1024))
            finally:r['Body'].close()
        print('RAW VERIFIED',record['nominal_utc'],Path(record['key']).name,record['bytes'],flush=True)
        return {**record,'local_file':str(target.resolve()),'sha256':digest}
    selected=[r for r in plan['files'] if not args.hsd_only or r['kind']=='HSD']
    with ThreadPoolExecutor(max_workers=4) as pool:files=list(pool.map(fetch,selected))
    original=json.loads((out/'protected_before.json').read_text())
    assert all(Path(p).exists() and [Path(p).stat().st_size,Path(p).stat().st_mtime_ns]==v for p,v in original.items())
    retained=[{'file':str(p.resolve()),'bytes':p.stat().st_size} for p in raw.rglob('*.part')]
    # An earlier whole-L2 request may have completed before switching to ROI ranges.
    extra=[{'file':str(p.resolve()),'bytes':p.stat().st_size,'sha256':sha(p)} for p in raw.rglob('*.nc')]
    actual=sum(r['bytes'] for r in files+refs+retained+extra)
    result={'files':files,'references':refs,'total_new_batch_bytes':actual,'planned_ceiling_bytes':total,'all_size_verified':True,
            'reference_hashes_match_installed_satpy':True,'protected_originals_unchanged_size_mtime':True,
            'raw_archives_are_complete_objects':True,'budget_bytes':plan['limit_bytes'],
            'retained_partial_files':retained,'retained_whole_l2':extra,'hsd_only':args.hsd_only}
    (raw/'manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (out/'download_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('FETCH COMPLETE',total,flush=True)


if __name__=='__main__':main()
