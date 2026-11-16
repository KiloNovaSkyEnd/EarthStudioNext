"""Choose certified per-frame asset checks or actual Blender sample checks."""
import json
from datetime import datetime
from pathlib import Path
from ges_next.production.assets import digest,write_json
from ges_next.production.template_certificate import folder_for,issue


def selection(package,blender):
    package=Path(package);root=package.parent.parent;execution=root/'execution.json'
    options=json.loads(execution.read_text(encoding='utf-8')) if execution.exists() else {}
    policy=options.get('verification',{})
    if not isinstance(policy,dict) or policy.get('mode','strict')!='batch':return 'blender',None,'strict'
    interval=policy.get('sample_interval',50)
    if type(interval) is not int or not 1<=interval<=100:raise ValueError('Blender sample interval must be1..100')
    from .queue_changes import effective
    plan=effective(root,json.loads((root/'plan.json').read_text(encoding='utf-8')))
    data=json.loads((package/'commit.json').read_text(encoding='utf-8'))
    # First qualified production scope; other grids/night profiles stay strict.
    if plan['project']['Production'].get('NightLightMetres')!=1000:return 'blender',None,'unqualified-night-profile'
    stamps=[s['utc'] for s in plan['steps']]
    if data['utc'] not in stamps:raise ValueError('Verified frame is outside the effective queue plan: '+data['utc'])
    index=stamps.index(data['utc']);when=datetime.fromisoformat(data['utc'].replace('Z','+00:00'))
    folder,_=folder_for(package,data,blender);certificate=folder/'certificate.json';receipt=folder/'receipt.json'
    if not receipt.exists():return 'blender',None,'new-template-contract'
    if not certificate.exists() or digest(certificate)!=json.loads(receipt.read_text())['sha256']:
        raise ValueError('Template certificate cache changed; inputs retained')
    gap=any(abs((when-datetime.fromisoformat(stamps[i].replace('Z','+00:00'))).total_seconds())>600
        for i in (index-1,index+1) if 0<=i<len(stamps))
    sample=index in (0,len(stamps)-1) or index%interval==0 or (when.hour%6==0 and when.minute==0) or gap
    if data['quality']['psnr_db']<37:sample=True
    return ('blender' if sample else 'assets'),certificate,('scheduled-or-boundary-sample' if sample else 'certified-frame')


def verify(workers,package):
    package=Path(package);kind,certificate,reason=selection(package,workers.blender)
    if kind=='blender':
        workers.verify_blender(package)
        # Strict mode is unchanged; batch samples also establish/update anchor proof.
        if reason!='strict' and reason!='unqualified-night-profile':issue(package,workers.blender)
        evidence=package/'blender_reopen.json'
    else:
        from ges_next.production.batch_assets import issue as issue_assets
        evidence=issue_assets(package,certificate)
    write_json(package/'verification_mode.json',dict(mode=kind,reason=reason,evidence=evidence.name,
        individually_opened_in_blender=kind=='blender'))
    return evidence
