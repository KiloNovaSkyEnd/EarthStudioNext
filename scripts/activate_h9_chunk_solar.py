"""Atomically publish exact-qualified tuning; running rows retain loaded settings."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges.earth_validation.project import save
from ges_next.isolation import require_writable


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    project=require_writable(ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700')
    qualification=project/'reports/chunk_solar_full_scan_qualification/results.json'
    result=read(qualification)
    if not (result.get('qualified') and result.get('all_16_native_tiles_exact')
            and result.get('source_compressed_l1_unchanged') and result.get('compute_chunk')==1024
            and result.get('shared_solar_factors') is True and len(result['comparisons'])==16):
        raise ValueError('Requires full native chunk/solar qualification')
    for tile in result['comparisons']:
        if not tile['all_rgba_and_grid_exact'] or digest(qualification.parent/'native'/tile['tile'])!=tile['sha256']:
            raise ValueError('Qualified native tile changed')
    for name in ['chunk_research_20261023','chunk_solar_twilight_20261023']:
        report=read(project/'reports'/name/'results.json')
        if not all(r['exact_rgba_grid_equal_to_committed'] for r in report['records']):
            raise ValueError('Native benchmark pixel parity failed')
    profile_path=project/'compute_profile.json';prior=read(profile_path);prior_sha=digest(profile_path)
    if prior.get('compute_chunk',512)!=512 or prior.get('shared_solar_factors',False):
        raise ValueError('Prior production settings differ from the audited baseline')
    if (project/'reports/chunk_solar_prior_profile.json').exists():
        raise ValueError('Activation already attempted; inspect previous activation evidence')
    scope=read(project/'reports/active_scope.json')
    if scope['generation']!=4 or read(project/'requested_scope.json')['generation']!=4:
        raise ValueError('Project scope/owner changed; do not overwrite a newer runtime')
    status=read(project/'reports/status.json')
    if digest(profile_path)!=prior_sha:raise ValueError('Production profile changed while waiting')
    save(project/'reports/chunk_solar_prior_profile.json',prior)
    profile=dict(prior,compute_chunk=1024,compute_chunk_pixel_parity_qualified=True,
        shared_solar_factors=True,solar_factors_pixel_parity_qualified=True,
        compute_chunk_qualification=str(qualification.relative_to(project)),
        solar_factors_qualification=str(qualification.relative_to(project)),
        chunk_solar_qualification_sha256=digest(qualification),
        updated_utc=datetime.now(timezone.utc).isoformat())
    save(profile_path,profile)
    sources=['ges/earth_validation/stock.py','ges/earth_validation/static_mask_cache.py',
        'ges/earth_validation/solar_shared.py','ges/earth_validation/solar_satpy_config/composites/ahi.yaml',
        'scripts/prepare_native_h9_disk.py']
    report=dict(stage='qualified_profile_published_actual_next_scan_pending',
        published_utc=datetime.now(timezone.utc).isoformat(),boundary_status=status,
        active_scope=scope,prior_profile_sha256=prior_sha,profile_sha256=digest(profile_path),
        qualification_sha256=digest(qualification),source_sha256={s:digest(ROOT/s) for s in sources},
        limits='Current rows retain their loaded settings. Subsequent native children read the new profile. '
        'The transition scan may contain both exactly-equivalent execution modes and is excluded from speed comparisons. '
        'No coordinator restart or weather/precision/grid/compression change. Actual activation must be observed.')
    save(project/'reports/chunk_solar_activation.json',report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
