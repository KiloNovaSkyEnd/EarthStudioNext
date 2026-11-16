"""Bounded read-only runtime4 activation checks; does not control production."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges.earth_validation.project import save


def read(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError,PermissionError):return {}


def main():
    project=ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700'
    target=project/'reports/throughput_runtime4_activation.json'
    proof=read(target);seen=set();began=time.monotonic()
    while time.monotonic()-began<1800:
        scope=read(project/'reports/active_scope.json')
        status=read(project/'reports/status.json')
        prefetch=read(project/'reports/prefetch_status.json')
        if scope.get('generation')==4 and scope.get('pipeline_prefetch'):
            proof['actual_lock_owner']=scope
            if 'lock' not in seen:
                seen.add('lock');print('RUNTIME4_LOCK',json.dumps(scope),flush=True)
            if status.get('stage')=='composing_native_H9':
                folder=project/'processed'/datetime.fromisoformat(status['utc'].replace('Z','+00:00')).strftime('%Y%m%dT%H%MZ')
                rows=[]
                for work in sorted(folder.glob('work*')):
                    resource=read(work/'reports/resource_usage.json')
                    if resource:rows.append(dict(configuration=read(work/'project.json'),resource=resource))
                active_rows=[r for r in rows if r['resource'].get('process_cpu_core_percent',0)>0]
                if (prefetch.get('state')=='downloading' and prefetch.get('utc')!=status['utc']
                        and active_rows and 'overlap' not in seen):
                    proof['observed_download_science_overlap']=dict(observed_utc=datetime.now(timezone.utc).isoformat(),
                        science_status=status,prefetch=prefetch,active_rows=active_rows)
                    seen.add('overlap');print('PREFETCH_OVERLAP',status['utc'],prefetch['utc'],flush=True)
                verified=[]
                for receipt in sorted(folder.glob('native_*.json')):
                    record=read(receipt);execution=record.get('execution',{})
                    if execution.get('night_io')!='mmap' or execution.get('gpu_calls',0)<=0:continue
                    with receipt.with_suffix('.tif').open('rb') as stream:
                        actual=hashlib.file_digest(stream,'sha256').hexdigest()
                    if actual!=record['sha256']:raise ValueError('Committed production tile hash differs')
                    verified.append(dict(receipt=str(receipt.relative_to(project)),sha256_verified=True,execution=execution))
                    if len(verified)>=2:break
                if len(verified)>=2:
                    proof['runtime4_committed_mmap_cuda_tiles']=verified
                    proof['runtime4_resource_samples']=rows
                    if 'tiles' not in seen:
                        seen.add('tiles');print('RUNTIME4_COMMITTED_MMAP_CUDA_TILES',len(verified),flush=True)
        proof['observed_utc']=datetime.now(timezone.utc).isoformat()
        if {'lock','overlap','tiles'}<=seen:
            proof.update(stage='actual_runtime4_lock_prefetch_overlap_and_committed_mmap_cuda_verified',
                limits='Runtime4 is actually computing and prefetching; two committed tile hashes verified. '
                'Full native quality qualification passed separately. End-to-end sequence speed remains to measure.')
            save(target,proof)
            print('RUNTIME4_ACTIVATION_VERIFIED',flush=True)
            return
        save(target,proof)
        time.sleep(2)
    raise TimeoutError('Bounded runtime observation expired; production left untouched')


if __name__=='__main__':main()
