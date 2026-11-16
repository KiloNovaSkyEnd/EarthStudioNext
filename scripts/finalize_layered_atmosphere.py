"""Seal V3 only after relocated-project checks have passed."""
import hashlib
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
out = root/'data/exports/H9_20261020T2240_Blender_v3'
seal = out/'delivery_checksums.json'
if seal.exists():
    raise FileExistsError('Preserve finalized V3')
evidence = out/'verification'
evidence.mkdir(exist_ok=False)
for name in ['layered_atmosphere_model_verification.json', 'layered_atmosphere_camera_verification.json',
             'layered_atmosphere_image_verification.json', 'blender_native_projection_verification.json']:
    data = json.loads((root/'reports'/name).read_text(encoding='utf-8'))
    assert data
    shutil.copy2(root/'reports'/name, evidence/name)
manifest = json.loads((out/'package_manifest.json').read_text(encoding='utf-8'))
for record in manifest['files']:
    with (out/record['path']).open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == record['sha256']
records = []
for path in sorted(out.rglob('*')):
    if path.is_file():
        with path.open('rb') as stream:
            records.append(dict(path=path.relative_to(out).as_posix(), bytes=path.stat().st_size,
                                sha256=hashlib.file_digest(stream, 'sha256').hexdigest()))
seal.write_text(json.dumps(dict(schema='earthstudio.blender.layered-atmosphere.v3',
    project='Earth_Studio_分层大气版.blend', source='Saved V2; unsaved Blender edits excluded',
    files=records, totalBytes=sum(r['bytes'] for r in records)), ensure_ascii=False, indent=2), encoding='utf-8')
print('V3_DELIVERY_READY', len(records), 'files', flush=True)
