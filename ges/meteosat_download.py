"""Authenticated, budget/byte-verified atomic SEVIRI native downloads."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import requests

from .catalog import utc_time
from .eumetsat_auth import authenticated_token
from .storage import load_config, preflight


def native_location(candidate):
    url=candidate['native_entry_url']
    parts=urlsplit(url)
    names=parse_qs(parts.query).get('name',[])
    if (parts.scheme!='https' or parts.hostname!='api.eumetsat.int' or
            len(names)!=1 or names[0]!=candidate['product_id']+'.nat' or
            '/' in names[0] or '\\' in names[0]):
        raise ValueError('Unexpected native product URL or filename')
    return url,names[0]


def response_ok(response):
    if response.status_code not in (200,206):
        # Never print response bodies, auth headers or token-bearing redirects.
        raise RuntimeError(f'EUMETSAT download HTTP {response.status_code}; no raw file published')


def probe_bytes(candidate, token, get=requests.get):
    url,_=native_location(candidate)
    with get(url,auth=token.auth,headers={'Range':'bytes=0-0','Accept-Encoding':'identity'},
             stream=True,timeout=45) as response:
        response_ok(response)
        match=re.fullmatch(r'bytes 0-0/(\d+)',response.headers.get('Content-Range',''))
        if response.status_code!=206 or not match or int(match[1])<=0:
            raise ValueError('Native byte size not verified by range response')
        return int(match[1])


def download_native(candidate, expected, root, cfg, token, get=requests.get):
    url,name=native_location(candidate)
    start=utc_time(candidate['scan_start_utc'])
    satellite='meteosat_'+candidate['platform'].lower()
    scene_id=f'{satellite}_{start:%Y%m%dT%H%M%SZ}'
    folder=Path(root)/scene_id; target=folder/name
    preflight(expected,folder,cfg)
    if target.exists():
        raise FileExistsError('Native target already exists; preserve it and verify its manifest before reuse')
    folder.mkdir(parents=True,exist_ok=True)
    partial=target.with_suffix('.nat.part')
    checksum=hashlib.sha256(); count=0
    try:
        with get(url,auth=token.auth,headers={'Accept-Encoding':'identity'},stream=True,timeout=(30,90)) as response:
            response_ok(response)
            if response.status_code!=200 or response.headers.get('Content-Encoding','identity') not in ('identity',''):
                raise ValueError('Expected an unencoded full native response')
            length=response.headers.get('Content-Length')
            if length is not None and int(length)!=expected:
                raise ValueError('Native response size differs from verified range size')
            with partial.open('wb') as output:
                for chunk in response.iter_content(1024*1024):
                    count+=len(chunk)
                    if count>expected:
                        raise IOError('Native stream exceeds verified size')
                    checksum.update(chunk); output.write(chunk)
        if count!=expected:
            raise IOError('Native stream incomplete; no raw file published')
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    manifest={**candidate,'kind':'authentic SEVIRI native scene; reader verification pending',
              'satellite':satellite,'scene_id':scene_id,'product':'SEVIRI-L1.5-native',
              'observed_utc':candidate['scan_start_utc'],'keys':[name],
              'local_files':[str(target.resolve())],'object_sizes':[expected],
              'total_bytes':expected,'sha256':checksum.hexdigest(),'downloaded':True,
              'downloaded_utc':datetime.now(timezone.utc).isoformat()}
    path=folder/'scene.json'; temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest,indent=2),encoding='utf-8'); temporary.replace(path)
    return path


def download_candidates(candidates):
    cfg=load_config(); token=authenticated_token()
    sizes=[probe_bytes(item,token) for item in candidates]
    preflight(sum(sizes),cfg.raw_dir,cfg)
    results=[]
    for item,size in zip(candidates,sizes):
        result=download_native(item,size,cfg.raw_dir,cfg,token)
        print('VERIFIED NATIVE:',result,flush=True); results.append(result)
    return results
