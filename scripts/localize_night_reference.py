"""Copy shared night inputs into this project, proving byte identity.

Only reference locators and their cache receipts change. Scientific image bytes
are never rewritten; original inputs and all previous metadata are retained.
"""
import json
from pathlib import Path
import shutil
import sys
from ges.earth_validation.archive import sha
from ges.earth_validation.night_background import build_vrt,validate_tile
from ges.earth_validation.project import save,check_disk

root=Path(sys.argv[1]).resolve(); folder=root/'raw/references/blackmarble_2016_500m'
backup=root/'reports/night_reference_localization'; backup.mkdir(exist_ok=True)
manifest=folder/'manifest.json'; vrt=folder/'global_500m.vrt'
if (backup/'complete.json').is_file():
    print('Already localized'); raise SystemExit(0)
for source in (manifest,vrt):
    target=backup/source.name
    if not target.exists(): shutil.copy2(source,target)
old=json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
old_vrt_sha=sha(backup/'global_500m.vrt'); new=json.loads(json.dumps(old)); copied=[]
for entry in new['tiles']:
    source=Path(entry['file']); destination=folder/f"BlackMarble_2016_{entry['tile']}_geo.tif"
    if not destination.is_file():
        check_disk(root,entry['bytes']); temporary=destination.with_suffix('.copying')
        shutil.copyfile(source,temporary)
        if sha(temporary)!=entry['sha256']: raise ValueError('Night reference copy hash mismatch')
        temporary.replace(destination); copied.append(str(destination))
    if sha(destination)!=entry['sha256']: raise ValueError('Night reference data changed')
    validate_tile(destination,entry['tile'])
    if source!=destination: entry['localized_from']=str(source)
    entry['file']=str(destination); entry['shared_existing']=False
build_vrt(vrt,new['tiles']); new_vrt_sha=sha(vrt)
save(manifest,new)
changed=[]
for path in (root/'processed/stock_geocolor').rglob('metadata.json'):
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('night_background_sha256')!=old_vrt_sha: continue
    original=backup/'metadata_before'/path.relative_to(root/'processed/stock_geocolor')
    if not original.exists(): original.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,original)
    record['night_background_sha256']=new_vrt_sha
    record['night_locator_migration']=str(backup/'complete.json')
    save(path,record); changed.append(str(path))
proxy=folder/'night_proxy_8km.json'
if proxy.is_file():
    if not (backup/proxy.name).exists(): shutil.copy2(proxy,backup/proxy.name)
    record=json.loads(proxy.read_text(encoding='utf-8')); record['source_manifest_sha256']=sha(manifest); save(proxy,record)
save(backup/'complete.json',{'old_vrt_sha256':old_vrt_sha,'new_vrt_sha256':new_vrt_sha,
    'all_eight_source_sha256_unchanged':True,'pixel_grids_unchanged':True,'copied':copied,
    'metadata_locators_updated':changed,'image_files_modified':False,'originals_preserved':True})
print('Night reference is self-contained on archive drive; image pixels unchanged')
