"""Restore an already verified global reference into permanent shared resources."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from ges.earth_validation.night_background import TILE_IDS,validate_tile,build_vrt
from ges_next.production.assets import write_json,digest
from ges_next.isolation import require_writable


def restore(source,target):
    source=Path(source);target=require_writable(target)
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if {r['tile'] for r in manifest['tiles']}!=set(TILE_IDS) or len(manifest['tiles'])!=8:
        raise ValueError('Eight verified reference tiles required')
    needed=sum(r['bytes'] for r in manifest['tiles'])
    target.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(target).free<needed+8*1024**3:raise ValueError('Insufficient reference restore space')
    rows=[]
    for entry in manifest['tiles']:
        name=f'BlackMarble_2016_{entry["tile"]}_geo.tif';original=source/name
        if not original.exists():original=Path(entry['file'])
        if original.stat().st_size!=entry['bytes']:raise ValueError('Source size changed')
        path=target/name
        if path.exists():
            if digest(path)!=entry['sha256']:raise ValueError('Existing shared reference differs; preserved')
        else:
            part=path.with_suffix('.restoring')
            if part.exists():raise FileExistsError('Existing partial restore preserved')
            h=hashlib.sha256()
            with original.open('rb') as src,part.open('xb') as dst:
                for block in iter(lambda:src.read(8*1024**2),b''):dst.write(block);h.update(block)
            if h.hexdigest()!=entry['sha256']:raise ValueError('Source/reference copy hash differs')
            part.replace(path)
        grid=validate_tile(path,entry['tile'])
        rows.append(dict(entry,file=str(path.resolve()),**grid))
        print(json.dumps(dict(tile=entry['tile'],bytes=entry['bytes'],hash_verified=True)),flush=True)
    vrt=build_vrt(target/'global_500m.vrt',rows)
    write_json(target/'manifest.json',dict(manifest,tiles=rows,vrt=str(vrt.resolve()),permanent_shared_reference=True))
    from ges_next.night_resources import configure,resolve
    configure(vrt);resolve(check_pixels=True)
    from ges_next.production.night_reference import reference_grid
    reference_grid(vrt,target/'global_1km.vrt',1000)
    return dict(path=str(vrt.resolve()),tiles=8,bytes=needed,reference_year=2016,resolution_m=500,
                independent_of_test_projects=True,source_modified=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('target',type=Path)
    args=parser.parse_args();result=restore(args.source,args.target)
    write_json(args.target/'restoration_receipt.json',result);print(json.dumps(result),flush=True)
