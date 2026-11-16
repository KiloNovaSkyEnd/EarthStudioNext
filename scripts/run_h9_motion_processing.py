"""Resumable, H9-only native sequence production; sources retained, isolated project."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import bz2
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges_next.isolation import require_writable
from ges.catalog import s3_client
from ges.earth_validation.project import save
from ges_next.h9_motion import observation_times
from ges_next.h9_decode import decode_originals
from ges_next.h9_prefetch import OneScanPrefetch,next_pending_scene

PROJECT=require_writable(ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700')
RESERVE=16*1024**3

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def update(stage,**values):
    data=dict(stage=stage,pid=os.getpid(),updated_utc=datetime.now(timezone.utc).isoformat(),**values)
    save(PROJECT/'reports/status.json',data)
    print(json.dumps(data,ensure_ascii=False),flush=True)

def check_space(incoming=0):
    free=shutil.disk_usage(PROJECT).free
    if free-incoming<RESERVE:raise RuntimeError(f'Storage safety stop: free={free}, incoming={incoming}, reserve={RESERVE}')

def fetch(obj,folder,client=None):
    target=folder/Path(obj['key']).name
    receipt=target.with_suffix(target.suffix+'.json')
    if target.is_file():
        if not receipt.exists():raise ValueError('Unreceipted original preserved: '+str(target))
        record=json.loads(receipt.read_text(encoding='utf-8'))
        if target.stat().st_size!=obj['bytes'] or record['etag']!=obj['etag'] or digest(target)!=record['sha256']:
            raise ValueError('Existing original differs from receipt: '+str(target))
        return target
    check_space(obj['bytes'])
    partial=target.with_suffix(target.suffix+'.part')
    identity=partial.with_suffix('.identity.json')
    expected={key:obj[key] for key in ['key','bytes','etag']}
    if partial.exists() and (not identity.exists() or json.loads(identity.read_text())!=expected):
        raise ValueError('Unidentified partial preserved: '+str(partial))
    save(identity,expected)
    for attempt in range(5):
        offset=partial.stat().st_size if partial.exists() else 0
        if offset>obj['bytes']:raise ValueError('Oversize partial preserved')
        if offset==obj['bytes']:break
        try:
            options=dict(Bucket='noaa-himawari9',Key=obj['key'],IfMatch=obj['etag'])
            if offset:options['Range']=f'bytes={offset}-'
            response=(client or s3_client()).get_object(**options)
            if response['ContentLength']!=obj['bytes']-offset or response['ETag']!=obj['etag']:
                raise ValueError('Provider changed after inventory')
            with response['Body'] as body,partial.open('ab') as stream:
                while chunk:=body.read(1024*1024):stream.write(chunk)
            if partial.stat().st_size!=obj['bytes']:raise IOError('Incomplete original retained for resume')
        except Exception:
            if attempt==4:raise
            time.sleep(min(2**attempt,10))
    etag=obj['etag'].strip('"')
    if '-' not in etag and len(etag)==32:
        with partial.open('rb') as stream:
            if hashlib.file_digest(stream,'md5').hexdigest()!=etag:raise ValueError('Original ETag/MD5 mismatch')
    sha=digest(partial);partial.replace(target)
    save(receipt,dict(**expected,sha256=sha,source='NOAA anonymous S3 Himawari9'))
    print('ORIGINAL_READY',target.name,obj['bytes'],flush=True)
    return target

def validate_master(folder,utc):
    master=json.loads((folder/'native_master.json').read_text(encoding='utf-8'))
    if master['utc']!=utc or master['shape']!=[22000,22000] or len(master['tiles'])!=16:
        raise ValueError('Native frame grid/time/coverage receipt invalid')
    for tile in master['tiles']:
        if digest(folder/tile['path'])!=tile['sha256']:raise ValueError('Native tile checksum failed')
    return master

def validate_plan(plan):
    if not isinstance(plan.get('pipeline_prefetch',False),bool):
        raise ValueError('pipeline_prefetch must be a boolean')
    expected=observation_times(plan['user_start'],plan['user_end'])
    if plan['satellite']!='himawari9' or len(plan['scenes'])!=len(expected):
        raise ValueError('Requires exact H9-only inventory for the declared interval')
    if [s['utc'] for s in plan['scenes']]!=[t.isoformat().replace('+00:00','Z') for t in expected]:
        raise ValueError('Time contract mismatch')
    missing=[s['utc'] for s in plan['scenes'] if s['missing']]
    if len(plan['scenes'])-len(missing)!=plan['complete_nodes'] or missing!=plan.get('acknowledged_missing_utc',[]):
        raise ValueError('Missing scans must be explicitly acknowledged, never replaced')
    for scene in plan['scenes']:
        if scene['missing']:continue
        names=[Path(o['key']).name for o in scene['objects']]
        if len(names)!=60 or len(set(names))!=60 or any(not n.startswith('HS_H09_') for n in names):
            raise ValueError('A complete scan requires60 unique H9 originals')
    return len(expected),missing

def fetch_scan(scene):
    stamp=datetime.fromisoformat(scene['utc'].replace('Z','+00:00'))
    raw=PROJECT/'raw'/stamp.strftime('%Y%m%dT%H%MZ');raw.mkdir(exist_ok=True)
    clients=threading.local()
    def fetch_in_thread(obj):
        if not hasattr(clients,'s3'):clients.s3=s3_client()
        return fetch(obj,raw,client=clients.s3)
    began=time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        sources=list(pool.map(fetch_in_thread,scene['objects']))
    save(PROJECT/'reports'/f'download_{stamp:%Y%m%dT%H%MZ}.json',
        dict(utc=scene['utc'],files=len(sources),seconds=time.monotonic()-began,workers=4,
             bytes=sum(o['bytes'] for o in scene['objects']),verified_before_decode=True))
    return sources


def verify_prefetched_sources(scene,sources):
    """Recheck originals after their longer asynchronous wait, before decoding."""
    if len(sources)!=len(scene['objects']):raise ValueError('Incomplete prefetched observation')
    for source,obj in zip(sources,scene['objects']):
        source=Path(source)
        if source.name!=Path(obj['key']).name:raise ValueError('Prefetched source order/identity differs')
        receipt=source.with_suffix(source.suffix+'.json')
        record=json.loads(receipt.read_text(encoding='utf-8'))
        if (source.stat().st_size!=obj['bytes'] or record['etag']!=obj['etag']
                or record['key']!=obj['key'] or digest(source)!=record['sha256']):
            raise ValueError('Prefetched original changed before decode')


_prefetch_report_lock=threading.Lock()


def record_prefetch(data):
    data=dict(data,pid=os.getpid(),updated_utc=datetime.now(timezone.utc).isoformat())
    with _prefetch_report_lock:
        save(PROJECT/'reports/prefetch_status.json',data)
        with (PROJECT/'reports/prefetch_events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(data)+'\n')


def execute(plan_name='provider_inventory.json'):
    plan=json.loads(require_writable(PROJECT/plan_name).read_text(encoding='utf-8'))
    total,missing=validate_plan(plan)
    preflight=json.loads((PROJECT/'storage_preflight.json').read_text(encoding='utf-8'))
    if not preflight['sufficient']:raise ValueError('Complete-project storage preflight required')
    for name in ['raw','processed','scratch','reports','exports']:(PROJECT/name).mkdir(exist_ok=True)
    save(PROJECT/'project.json',dict(start_utc=plan['start_utc'],end_utc=plan['end_utc'],
        allowed_satellites=['himawari9'],scope='H9 observed full disk only',reserve_free_bytes=RESERVE,
        weather_frame_count=plan['complete_nodes'],nominal_node_count=total,missing_observations_utc=missing,
        nominal_cadence_minutes=10,originals_retained=True,scope_generation=plan.get('generation',1),
        pipeline_prefetch=plan.get('pipeline_prefetch',False)))
    save(PROJECT/'reports/active_scope.json',dict(plan_file=plan_name,total_nodes=total,
        observed_nodes=plan['complete_nodes'],missing_observations_utc=missing,generation=plan.get('generation',1),
        user_start=plan['user_start'],user_end=plan['user_end'],pid=os.getpid(),
        pipeline_prefetch=plan.get('pipeline_prefetch',False)))
    reference=ROOT.parent/'GlobalSatelliteEarthStudio/data/raw/reference'
    if not (reference/'pyspectral/rsr').is_dir():raise FileNotFoundError('Qualified spectral references missing')
    from ges.earth_validation.night_background import acquire
    update('acquiring_500m_night_reference',total_nodes=total)
    night=acquire(PROJECT,reference/'blackmarble_500m_v1/BlackMarble_2016_D1_geo.tif')
    with OneScanPrefetch(fetch_scan,check_space,record_prefetch,
            enabled=plan.get('pipeline_prefetch',False)) as prefetch:
        execute_scans(plan,total,missing,night,reference,prefetch)


def execute_scans(plan,total,missing,night,reference,prefetch):
    frames=[]
    for index,scene in enumerate(plan['scenes'],1):
        utc=scene['utc'];stamp=datetime.fromisoformat(utc.replace('Z','+00:00'))
        if scene['missing']:
            save(PROJECT/'reports'/f'missing_{stamp:%Y%m%dT%H%MZ}.json',dict(utc=utc,state='missing_provider_observation',
                substituted=False,details=scene['missing']))
            continue
        native=PROJECT/'processed'/stamp.strftime('%Y%m%dT%H%MZ')
        if (native/'native_master.json').is_file():
            master=validate_master(native,utc)
        else:
            update('downloading_H9_scan',node=index,total_nodes=total,utc=utc)
            sources=prefetch.take(scene)
            if sources is None:sources=fetch_scan(scene)
            else:verify_prefetched_sources(scene,sources)
            check_space(4*1024**3)
            # Decoded working copies are disposable; byte-exact compressed L1 stays retained.
            with tempfile.TemporaryDirectory(prefix='decoded_'+stamp.strftime('%H%M')+'_',dir=PROJECT/'scratch') as temp:
                temp=Path(temp).resolve()
                if not temp.is_relative_to((PROJECT/'scratch').resolve()):raise ValueError('Decoded scratch outside project')
                update('decoding_H9_scan',node=index,total_nodes=total,utc=utc,decode_workers=4)
                decode_start=time.monotonic()
                decode_originals(sources,temp,workers=4)
                save(PROJECT/'reports'/f'decode_{stamp:%Y%m%dT%H%MZ}.json',
                    dict(utc=utc,workers=4,seconds=time.monotonic()-decode_start,originals_retained=True))
                update('composing_native_H9',node=index,total_nodes=total,utc=utc)
                candidate=next_pending_scene(plan['scenes'],index,
                    lambda s:(PROJECT/'processed'/datetime.fromisoformat(s['utc'].replace('Z','+00:00')).strftime('%Y%m%dT%H%MZ')/'native_master.json').is_file())
                prefetch.start(candidate)
                command=[sys.executable,'-X','utf8',str(ROOT/'scripts/prepare_native_h9_disk.py'),
                    '--utc',utc,'--raw',str(temp),'--reference',str(reference),'--night',str(night),
                    '--output',str(native),'--shared-static-cache',str(PROJECT/'shared_static'),
                    '--scope-generation',str(plan.get('generation',1))]
                with (PROJECT/'reports'/f'compose_{index:02}.log').open('a',encoding='utf-8') as stream:
                    subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
            master=validate_master(native,utc)
        frames.append(dict(utc=utc,path=str(native/'native_master.json'),scan_start=master['sourceBands']['B03']['startUtc'],
                           scan_end=master['sourceBands']['B03']['endUtc']))
        save(PROJECT/'reports/native_frames.json',dict(completed=len(frames),total=plan['complete_nodes'],
            nominal_nodes=total,missing_observations_utc=missing,frames=frames))
        update('native_frame_committed',node=index,total_nodes=total,utc=utc)
    save(PROJECT/'exports/weather_sequence.json',dict(satellite='himawari9',frames=frames,native_shape=[22000,22000],
        cadence_minutes=10,nominal_nodes=total,missing_observations_utc=missing,
        camera_independent=True,interpolated_weather=False,blender_playback_verified=False))
    update('native_weather_sequence_ready',completed=len(frames),total_nodes=total,
           next_step='Blender sequence binding and actual multi-time camera/render acceptance; not yet delivered')

def main():
    import msvcrt
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',default='provider_inventory.json')
    parser.add_argument('--wait-for-lock',action='store_true')
    parser.add_argument('--after-native-utc',help='Queue a runtime handoff only after this full native frame commits')
    args=parser.parse_args()
    (PROJECT/'reports').mkdir(exist_ok=True)
    if args.after_native_utc:
        plan=json.loads(require_writable(PROJECT/args.plan).read_text(encoding='utf-8'))
        validate_plan(plan)
        stamp=datetime.fromisoformat(args.after_native_utc.replace('Z','+00:00'))
        if args.after_native_utc not in [s['utc'] for s in plan['scenes'] if not s['missing']]:
            raise ValueError('Handoff boundary must be an actual requested H9 scan')
        native=PROJECT/'processed'/stamp.strftime('%Y%m%dT%H%MZ')
        while not (native/'native_master.json').exists():
            save(PROJECT/'reports/runtime_handoff.json',dict(stage='waiting_for_complete_native_frame',
                boundary_utc=args.after_native_utc,replacement_pid=os.getpid(),plan=args.plan))
            time.sleep(2)
        validate_master(native,args.after_native_utc)
        current=json.loads((PROJECT/'requested_scope.json').read_text(encoding='utf-8'))
        if plan['generation']<current['generation']:raise ValueError('Obsolete runtime upgrade cannot replace newer scope')
        save(PROJECT/'requested_scope.json',dict(generation=plan['generation'],plan=args.plan,
            user_start=plan['user_start'],user_end=plan['user_end'],nominal_nodes=len(plan['scenes']),observed_nodes=plan['complete_nodes'],
            missing_utc=plan['acknowledged_missing_utc'],replacement_pid=os.getpid(),reason='Qualified hardware runtime upgrade at full-scan boundary'))
        save(PROJECT/'reports/runtime_handoff.json',dict(stage='runtime_upgrade_requested',
            boundary_utc=args.after_native_utc,replacement_pid=os.getpid(),plan=args.plan))
    with (PROJECT/'reports/processing.lock').open('a+b') as lock:
        while True:
            try:
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError:
                if not args.wait_for_lock:raise
                save(PROJECT/'reports/scope_handoff.json',dict(stage='waiting_for_current_scan_boundary',
                    replacement_pid=os.getpid(),plan=args.plan,updated_utc=datetime.now(timezone.utc).isoformat()))
                time.sleep(2)
        try:
            if args.wait_for_lock:save(PROJECT/'reports/scope_handoff.json',dict(stage='replacement_acquired_project_lock',
                replacement_pid=os.getpid(),plan=args.plan,updated_utc=datetime.now(timezone.utc).isoformat()))
            execute(args.plan)
        except Exception as error:
            update('failed',error=str(error),resume_supported=True)
            raise

if __name__=='__main__':main()
