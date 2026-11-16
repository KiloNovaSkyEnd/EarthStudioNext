"""Read-only preparation for a future night pseudo-VIS adapter. Never runs a model."""
import hashlib,json,re
from datetime import datetime,timezone

def validate_proposal(proposal):
    if proposal.get('schema')!='earthstudio.pseudovis.proposal.v1':raise ValueError('Unknown pseudo-VIS proposal schema')
    if proposal.get('enabled') is not False:raise ValueError('Research proposal cannot enable a production algorithm')
    if not proposal.get('algorithm_id') or not proposal.get('version'):raise ValueError('Algorithm/version identity required')
    bands=proposal.get('required_ir_bands',[])
    if not bands or len(set(bands))!=len(bands) or any(not re.fullmatch(r'B\d{2}',b) for b in bands):raise ValueError('Explicit distinct IR bands required')
    if not re.fullmatch(r'[a-f0-9]{64}',proposal.get('weights_sha256','')):raise ValueError('Pinned model fingerprint required')
    if not proposal.get('source_sha256') or any(not re.fullmatch(r'[a-f0-9]{64}',v) for v in proposal['source_sha256'].values()):raise ValueError('Pinned adapter source fingerprints required')
    sun=proposal['fixed_virtual_sun']
    if not 0<=sun['sza']<90 or not -180<=sun['azimuth']<=180:raise ValueError('Explicit valid fixed virtual illumination required')
    return proposal

def assess_step(step,proposal,existing_bands):
    proposal=validate_proposal(proposal)
    when=datetime.fromisoformat(step['utc'].replace('Z','+00:00'))
    if when.utcoffset()!=timezone.utc.utcoffset(when):raise ValueError('Exact UTC required')
    selected={b:set() for b in proposal['required_ir_bands']};wrong_time=[]
    pattern=re.compile(r'HS_H09_(\d{8})_(\d{4})_(B\d{2})_FLDK_R\d+_S(\d{2})10\.DAT\.bz2$')
    for obj in step['objects']:
        match=pattern.search(obj['key'])
        if match and match[3] in selected:
            if match[1]+match[2]!=when.strftime('%Y%m%d%H%M'):wrong_time.append(obj['key']);continue
            selected[match[3]].add(int(match[4]))
    missing={b:sorted(set(range(1,11))-segments) for b,segments in selected.items() if segments!=set(range(1,11))}
    extra=sorted(set(proposal['required_ir_bands'])-set(existing_bands))
    return dict(algorithm_id=proposal['algorithm_id'],version=proposal['version'],enabled=False,integration_ready=False,
        missing_segments=missing,wrong_time_objects=wrong_time,additional_bands=extra,additional_objects_per_scan=len(extra)*10,
        minimum_combined_objects_per_scan=len(set(existing_bands)|set(proposal['required_ir_bands']))*10,
        input_coverage_complete=not missing and not wrong_time,required_qualification=proposal['pending_qualification'])

def cache_identity(step,proposal,grid_id):
    validate_proposal(proposal)
    if not grid_id:raise ValueError('Exact target grid identity required')
    value=dict(algorithm_id=proposal['algorithm_id'],version=proposal['version'],weights=proposal['weights_sha256'],
        source=proposal['source_sha256'],sun=proposal['fixed_virtual_sun'],utc=step['utc'],grid=grid_id,
        inputs=sorted([(o['bucket'],o['key'],o['etag'],o['bytes']) for o in step['objects']]))
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
