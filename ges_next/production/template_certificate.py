"""Immutable certification from a real independently reopened anchor scene."""
import json,sqlite3,shutil,stat
from pathlib import Path
from .assets import digest,record,verify_assets,write_json
from .certificate_identity import identity,key,asset_identity
from ..pipeline.locking import exclusive


def folder_for(package,data,blender):
    contract=identity(data,blender)
    return Path(package).parent.parent/'template_certificates'/key(contract),contract


def issue(package,blender):
    package=Path(package);data=json.loads((package/'commit.json').read_text(encoding='utf-8'))
    proof_path=package/'blender_reopen.json';proof=json.loads(proof_path.read_text(encoding='utf-8'))
    if proof['schema']!='earthstudio.blender.production_reopen.v1' or proof.get('test_fixture_only'):
        raise ValueError('Full fresh Blender anchor required')
    from .verification import validate_reopen
    with sqlite3.connect((package.parent/'production_journal.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;job=dict(db.execute('SELECT * FROM jobs WHERE root=?',(str(package),)).fetchone())
        step=dict(db.execute('SELECT * FROM steps WHERE job=? AND utc=?',(job['id'],data['utc'])).fetchone())
    validate_reopen(job,step,proof_path)
    folder,contract=folder_for(package,data,blender);folder.mkdir(parents=True,exist_ok=True)
    with exclusive(folder/'certificate.lock',wait=True):
        target=folder/'certificate.json';receipt=folder/'receipt.json'
        if receipt.exists():
            expected=json.loads(receipt.read_text(encoding='utf-8'))
            if digest(target)!=expected['sha256']:raise ValueError('Template certificate changed')
            return target
        certificate=dict(schema='earthstudio.template_certificate.v1',identity=contract,key=key(contract),
            anchor=str(package.resolve()),anchor_manifest_sha256=digest(package/'commit.json'),
            anchor_evidence=record(package,proof_path,'anchor-blender-proof'),profile=json.loads(job['profile']),
            blender_version=proof['blender_version'],verified_capabilities=proof['verified_capabilities'])
        write_json(target,certificate);write_json(receipt,dict(sha256=digest(target)))
        target.chmod(stat.S_IREAD|stat.S_IRGRP|stat.S_IROTH)
        return target


def copy_to(package,source):
    target=Path(package)/'verification_template.json';expected=digest(source)
    if target.exists():
        if digest(target)!=expected:raise ValueError('Existing per-frame certificate differs')
    else:shutil.copyfile(source,target)
    return record(package,target,'template-certificate')


def validate(package,data,profile,proof,require_current=True):
    verify_assets(package,[proof['certificate']])
    certificate=json.loads((Path(package)/proof['certificate']['path']).read_text(encoding='utf-8'))
    if certificate.get('schema')!='earthstudio.template_certificate.v1':raise ValueError('Invalid template certificate')
    contract=certificate['identity']
    if certificate['key']!=key(contract) or any(contract.get(k)!=v for k,v in asset_identity(data).items()):
        raise ValueError('Certified asset contract differs from this frame')
    if require_current and identity(data,contract['blender_executable'])!=contract:
        raise ValueError('Template/engine/profile changed; full Blender check required')
    if certificate['profile']!=profile:raise ValueError('Template certification profile differs')
    anchor=Path(certificate['anchor']);evidence=certificate['anchor_evidence']
    if anchor.resolve()==Path(package).resolve():raise ValueError('Certified frame cannot certify itself')
    if digest(anchor/'commit.json')!=certificate['anchor_manifest_sha256']:raise ValueError('Anchor manifest changed')
    verify_assets(anchor,[evidence])
    anchor_proof=json.loads((anchor/evidence['path']).read_text(encoding='utf-8'))
    if anchor_proof['schema']!='earthstudio.blender.production_reopen.v1':raise ValueError('Anchor must be a real full Blender reopen')
    anchor_data=json.loads((anchor/'commit.json').read_text(encoding='utf-8'))
    from .verification import validate_reopen
    anchor_job=dict(root=str(anchor),profile=json.dumps(profile))
    validate_reopen(anchor_job,dict(manifest=str(anchor/'commit.json'),hash=certificate['anchor_manifest_sha256']),anchor/evidence['path'],decode_images=False)
    if any(contract.get(k)!=v for k,v in asset_identity(anchor_data).items()):raise ValueError('Anchor contract differs from frame')
    if not set(profile['required_capabilities']).issubset(certificate['verified_capabilities']):raise ValueError('Template editing capabilities incomplete')
    return True
