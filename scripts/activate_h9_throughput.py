"""Publish exact-qualified H9 throughput settings and queue a scan-boundary handoff."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges.earth_validation.project import save
from ges_next.isolation import require_writable


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    project=require_writable(ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700')
    qualification=project/'reports/throughput_runtime4_qualification/results.json'
    report=json.loads(qualification.read_text(encoding='utf-8'))
    if not (report.get('qualified') and report.get('all_16_native_tiles_exact')
            and report.get('source_compressed_l1_unchanged') and len(report['comparisons'])==16):
        raise ValueError('Complete exact full-scan qualification required')
    for tile in report['comparisons']:
        if not tile['all_rgba_and_grid_exact'] or digest(qualification.parent/'native'/tile['tile'])!=tile['sha256']:
            raise ValueError('Qualification tile changed')
    scope=json.loads((project/'requested_scope.json').read_text(encoding='utf-8'))
    if scope['generation']!=3:raise ValueError('Runtime4 activation is only valid from the audited generation3')
    active=json.loads((project/'reports/active_scope.json').read_text(encoding='utf-8'))
    if active['generation']!=3:raise ValueError('Current project lock owner differs from audited runtime')
    import psutil
    if not psutil.pid_exists(active['pid']):raise ValueError('Expected production coordinator is no longer running')
    plan=json.loads((project/active['plan_file']).read_text(encoding='utf-8'))
    from scripts.run_h9_motion_processing import validate_plan
    validate_plan(plan)
    new_plan=dict(plan,generation=4,pipeline_prefetch=True)
    required_raw=0;pending=0
    for scene in plan['scenes']:
        if scene['missing']:continue
        stamp=datetime.fromisoformat(scene['utc'].replace('Z','+00:00')).strftime('%Y%m%dT%H%MZ')
        if not (project/'processed'/stamp/'native_master.json').is_file():pending+=1
        for obj in scene['objects']:
            path=project/'raw'/stamp/Path(obj['key']).name
            required_raw+=max(0,obj['bytes']-(path.stat().st_size if path.is_file() else 0))
    # Conservative 800MiB per still-uncommitted native scan, same or greater
    # than the prior 0.8GB forecast; retain originals and working/safety buffers.
    required=required_raw+pending*800*1024**2+10*1024**3+16*1024**3+4*1024**3
    available=shutil.disk_usage(project).free
    budget=dict(checked_utc=datetime.now(timezone.utc).isoformat(),available_free_bytes=available,
        remaining_original_bytes=required_raw,remaining_native_scan_count=pending,
        forecast_native_bytes_per_scan=800*1024**2,working_allowance_bytes=10*1024**3,
        reserve_bytes=16*1024**3,prefetch_extra_allowance_bytes=4*1024**3,
        required_additional_free_bytes=required,sufficient=available>=required,
        inventory_and_scope_unchanged=True,originals_retained=True)
    save(project/'reports/throughput_runtime4_storage_preflight.json',budget)
    if not budget['sufficient']:raise RuntimeError('Runtime4 prefetch storage budget does not fit')
    profile=json.loads((project/'compute_profile.json').read_text(encoding='utf-8'))
    backup=project/'reports/throughput_runtime4_prior_profile.json'
    if backup.exists():raise ValueError('Activation already attempted; inspect saved state before retrying')
    save(backup,profile)
    profile.update(night_io='mmap',night_io_pixel_parity_qualified=True,
        night_io_qualification=str(qualification.relative_to(project)),
        night_io_qualification_sha256=digest(qualification),
        updated_utc=datetime.now(timezone.utc).isoformat())
    save(project/'provider_inventory_12h_runtime4.json',new_plan)
    save(project/'compute_profile.json',profile)
    status=json.loads((project/'reports/status.json').read_text(encoding='utf-8'))
    boundary=status['utc']
    if boundary not in [s['utc'] for s in plan['scenes'] if not s['missing']]:
        raise ValueError('Runtime boundary must be an existing requested real observation')
    command=[sys.executable,'-X','utf8','-u',str(ROOT/'scripts/run_h9_motion_processing.py'),
        '--plan','provider_inventory_12h_runtime4.json','--wait-for-lock','--after-native-utc',boundary]
    with (project/'reports/processing_runtime4.stdout.log').open('xb') as stdout,\
            (project/'reports/processing_runtime4.stderr.log').open('xb') as stderr:
        process=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    science=['ges/earth_validation/stock.py','ges/earth_validation/cuda_night.py',
        'scripts/prepare_native_h9_disk.py','scripts/run_h9_motion_processing.py',
        'ges_next/h9_prefetch.py','ges_next/h9_parallel.py']
    activation=dict(stage='replacement_launched_waiting_for_scan_boundary',launcher_pid=process.pid,
        previous_coordinator_pid=active['pid'],boundary_utc=boundary,generation=4,
        plan='provider_inventory_12h_runtime4.json',qualified_native_seconds=report['experimental_native_seconds'],
        qualification_sha256=digest(qualification),profile_sha256=digest(project/'compute_profile.json'),
        source_sha256={name:digest(ROOT/name) for name in science},storage_preflight=budget,
        limits='Profile published; actual lock acquisition, mmap receipts and overlapping prefetch still require observation.')
    save(project/'reports/throughput_runtime4_activation.json',activation)
    print(json.dumps(activation,indent=2),flush=True)


if __name__=='__main__':main()
