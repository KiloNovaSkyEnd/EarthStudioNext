"""Reacquire only the recipe's one scan into a fresh resumable candidate directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from .assets import digest,write_json
from .rebuild_recipe import validate


def restore(recipe_path,output,client,report=lambda value:None):
    from ges_next.isolation import require_writable
    recipe_path=Path(recipe_path);recipe=json.loads(recipe_path.read_text(encoding='utf-8'));when=validate(recipe)
    root=require_writable(output);marker=root/'reacquisition_job.json'
    identity=dict(recipe_sha256=digest(recipe_path),utc=recipe['utc'])
    if root.exists() and any(root.iterdir()):
        if not marker.exists() or json.loads(marker.read_text(encoding='utf-8'))!=identity:
            raise ValueError('Existing directory is not this reacquisition job')
    root.mkdir(parents=True,exist_ok=True)
    total=sum(item['bytes'] for item in recipe['inputs'])
    if shutil.disk_usage(root).free < total+8*1024**3: raise ValueError('Insufficient space for this scan plus8GiB reserve')
    write_json(marker,identity)
    from .owned_files import owned_path
    folder=root/'raw'/when.strftime('%Y%m%dT%H%MZ')
    owned_path(root,folder/'ownership-check','l1');folder.mkdir(parents=True,exist_ok=True)
    for index,item in enumerate(recipe['inputs']):
        target=folder/Path(item['key']).name
        owned_path(root,target,'l1')
        if target.exists():
            if target.stat().st_size!=item['bytes'] or digest(target)!=item['sha256']: raise ValueError('Existing candidate input differs')
        else:
            part=target.with_name(target.name+'.part');sha=hashlib.sha256();size=0
            owned_path(root,part,'l1')
            if part.exists() and part.stat().st_nlink!=1: raise ValueError('Shared partial file preserved')
            response=client.get_object(Bucket=item['bucket'],Key=item['key'],IfMatch=item['etag'])
            body=response['Body']
            try:
                with part.open('wb') as stream:
                    while chunk:=body.read(1024*1024):
                        size+=len(chunk)
                        if size>item['bytes']: raise ValueError('Provider payload larger than pinned object')
                        sha.update(chunk);stream.write(chunk)
                    stream.flush();os.fsync(stream.fileno())
                if size!=item['bytes'] or sha.hexdigest()!=item['sha256']: raise ValueError('Provider bytes changed; original sequence preserved')
                part.replace(target)
            finally: body.close()
        write_json(Path(str(target)+'.json'),dict(key=item['key'],bytes=item['bytes'],etag=item['etag'],sha256=item['sha256'],source='NOAA anonymous S3 Himawari9'))
        report(dict(phase='reacquiring-one-scan',utc=recipe['utc'],completed=index+1,total=60))
    write_json(root/'status.json',dict(phase='l1-restored-awaiting-new-production',utc=recipe['utc'],source_recipe=str(recipe_path.resolve())))
    return root


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('recipe',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    client=boto3.client('s3',region_name='us-east-1',config=Config(signature_version=UNSIGNED,connect_timeout=5,read_timeout=30,retries={'max_attempts':1}))
    restore(args.recipe,args.output,client,lambda value:print(json.dumps(value),flush=True))


if __name__=='__main__': main()
