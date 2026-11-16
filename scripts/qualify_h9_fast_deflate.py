"""Qualify full-frame lossless level1; publish only measured speed/storage success."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges.earth_validation.project import save
from ges_next.h9_lossless_encoding import encode_exact
from ges_next.isolation import require_writable


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=require_writable(ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700')
    out=require_writable(p/'reports/full_native_fast_deflate_20261023');out.mkdir(exist_ok=False)
    if shutil.disk_usage(out).free<28*1024**3:raise RuntimeError('Bounded encoding experiment needs28GiB free')
    original_profile=(p/'compute_profile.json').read_text(encoding='utf-8')
    source=p/'processed/20261020T1940Z'
    master=json.loads((source/'native_master.json').read_text())
    if len(master['tiles'])!=16 or master['shape']!=[22000,22000]:raise ValueError('Complete native reference required')
    hashes={t['path']:t['sha256'] for t in master['tiles']}
    for name,sha in hashes.items():
        if digest(source/name)!=sha:raise ValueError('Original native receipt checksum differs')
    records=[]
    central=source/'native_05500_05500.tif'
    for i,level in enumerate([6,1,1,6]):
        result=encode_exact(central,out/f'control_{i}_level{level}.tif',level)
        records.append(result);print(json.dumps(dict(control=i,**result)),flush=True)
    full=[]
    for index,tile in enumerate(master['tiles']):
        pair={}
        # Alternate order; both writes use identical retained native pixels.
        for level in ([6,1] if index%2==0 else [1,6]):
            folder=out/f'level{level}';folder.mkdir(exist_ok=True)
            result=encode_exact(source/tile['path'],folder/tile['path'],level)
            result['sha256']=digest(folder/tile['path']);pair[str(level)]=result
        full.append(dict(tile=tile['path'],levels=pair))
        save(out/'progress.json',dict(tiles_checked=len(full),total=16))
        print(json.dumps(dict(tile=tile['path'],levels=pair)),flush=True)
    for name,sha in hashes.items():
        if digest(source/name)!=sha:raise ValueError('Original native master changed during encoding experiment')
    sums={str(level):dict(write_seconds=sum(t['levels'][str(level)]['write_seconds'] for t in full),
        bytes=sum(t['levels'][str(level)]['bytes'] for t in full)) for level in [1,6]}
    control_old=min(r['write_seconds'] for r in records if r['level']==6)
    control_new=max(r['write_seconds'] for r in records if r['level']==1)
    speed_pass=control_new<control_old*.9 and sums['1']['write_seconds']<sums['6']['write_seconds']*.9
    remaining=json.loads((p/'reports/native_frames.json').read_text())
    count=remaining['total']-remaining['completed']
    plan=json.loads((p/'provider_inventory_12h_runtime4.json').read_text())
    incoming=sum(o['bytes'] for s in plan['scenes'] for o in s['objects']
        if not (p/'raw'/datetime.fromisoformat(s['utc'].replace('Z','+00:00')).strftime('%Y%m%dT%H%MZ')/Path(o['key']).name).exists())
    # Forecast with50% headroom for changing weather/content; keep existing hard
    # per-stage storage stops and16GiB reserve independently of this forecast.
    output_forecast=int(sums['1']['bytes']*1.5*count)
    needed=output_forecast+incoming+20*1024**3
    space_pass=shutil.disk_usage(p).free>=needed
    report=dict(qualified=True,created_utc=datetime.now(timezone.utc).isoformat(),utc=master['utc'],
        native_shape=master['shape'],all_16_rgba_grid_mask_and_metadata_exact=True,
        original_16_hashes_unchanged=True,controls=records,tiles=full,sums=sums,
        conservative_control_time_reduction=1-control_new/control_old,
        full_encode_time_reduction=1-sums['1']['write_seconds']/sums['6']['write_seconds'],
        storage_increase_fraction=sums['1']['bytes']/sums['6']['bytes']-1,
        speed_gate_passed=speed_pass,storage_gate_passed=space_pass,
        storage_forecast=dict(remaining_frames=count,remaining_inventory_bytes=incoming,
            output_bytes_with50percent_margin=output_forecast,needed_including20GiB_reserve=needed,
            free_bytes=shutil.disk_usage(p).free),
        limits='Encoding-only timing on retained native pixels; no claim of equal full science wall-time gain. '
            'L1 and scientific graphs unchanged. Future output sizes are forecasts, existing disk stops remain.')
    save(out/'results.json',report)
    activation=dict(activated=False,quality_passed=True,speed_passed=speed_pass,storage_passed=space_pass)
    growth_allowed=json.loads(original_profile).get('allow_storage_growth',True)
    activation['storage_growth_allowed']=growth_allowed
    if speed_pass and space_pass and growth_allowed:
        if (p/'compute_profile.json').read_text(encoding='utf-8')!=original_profile:
            raise RuntimeError('Concurrent compute-profile update; qualification retained, no overwrite')
        profile=json.loads(original_profile)
        if profile.get('zlevel',6)!=6:raise ValueError('Expected existing level6 profile')
        save(out/'prior_profile.json',profile)
        profile.update(zlevel=1,lossless_level_pixel_parity_qualified=True,
            lossless_level_qualification=str((out/'results.json').relative_to(p)),
            lossless_level_qualification_sha256=digest(out/'results.json'),
            lossless_level_updated_utc=datetime.now(timezone.utc).isoformat())
        save(p/'compute_profile.json',profile)
        activation.update(activated=True,scope='Next native process; existing processes retain settings',
            compute_workers_unchanged=profile['compute_workers'],zlevel=1)
    save(out/'activation.json',activation)
    print(json.dumps(dict(sums=sums,activation=activation)),flush=True)


if __name__=='__main__':main()
