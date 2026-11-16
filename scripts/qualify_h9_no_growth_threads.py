"""Same-input full native4/8 encoder comparison; fixed lossless level6."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges.earth_validation.project import save
from ges_next.isolation import require_writable


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    p=require_writable(ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700')
    out=require_writable(p/'reports/full_no_growth_threads_20261023');out.mkdir(exist_ok=False)
    profile_path=p/'compute_profile.json';original=profile_path.read_text()
    profile=json.loads(original)
    if profile['zlevel']!=6 or profile.get('allow_storage_growth') is not False:
        raise ValueError('No-growth fixed-level6 policy required')
    # Drain the already authorized single-scan prefetch before either control;
    # otherwise only the first run could compete with download/hash work.
    draining=time.monotonic()
    current=json.loads((p/'reports/status.json').read_text())['utc']
    while True:
        prefetch=json.loads((p/'reports/prefetch_status.json').read_text())
        if prefetch.get('state')=='failed':raise RuntimeError('Production prefetch failed; release experiment window')
        if prefetch.get('state')=='ready' and prefetch.get('utc','')>current:break
        if time.monotonic()-draining>240:raise TimeoutError('Background prefetch not idle within4 minutes')
        time.sleep(2)
    prefetch_wait=time.monotonic()-draining
    measurements=[]
    for threads in [4,8]:
        trial=out/f'threads{threads}'
        command=[sys.executable,'-X','utf8','-u',str(ROOT/'scripts/qualify_h9_throughput.py'),
            '--project',str(p),'--output',str(trial),'--compute-chunk','1024','--shared-solar',
            '--parallel-rows','2','--gdal-threads',str(threads),
            '--decoded-directory',str(p/'reports/workers_shared_research_20261023/private_decoded_o3wd4x_z')]
        with (out/f'threads{threads}.log').open('w',encoding='utf-8') as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        result=json.loads((trial/'results.json').read_text())
        admission=json.loads((trial/'native/parallel_row_admission.json').read_text())
        if admission['admitted_rows']!=2:raise RuntimeError('Full-frame comparison deferred: dual processes not admitted')
        if not result['qualified'] or len(result['comparisons'])!=16:raise RuntimeError('Whole native parity not qualified')
        if any(t['execution']['compute_admission']['admitted_workers']!=6 for t in result['comparisons']):
            raise RuntimeError('Full comparison deferred: actual compute threads differ')
        measurements.append(result)
        print(json.dumps(dict(gdal_threads=threads,seconds=result['experimental_native_seconds'],qualified=True)),flush=True)
        # Only files created in this experiment are disposed, after full parity
        # and SHA receipts are recorded. No permanent weather master is touched.
        for t in result['comparisons']:
            path=(trial/'native'/t['tile']).resolve()
            if not path.is_relative_to((trial/'native').resolve()):raise ValueError('Candidate outside experiment')
            path.unlink()
    a,b=measurements
    old={t['tile']:t['bytes'] for t in a['comparisons']}
    new={t['tile']:t['bytes'] for t in b['comparisons']}
    no_growth=old==new
    reduction=1-b['experimental_native_seconds']/a['experimental_native_seconds']
    decision=dict(created_utc=datetime.now(timezone.utc).isoformat(),utc=a['utc'],
        both_full_scans_pixel_grid_exact=True,all_16_encoded_file_sizes_equal=no_growth,
        baseline_seconds=a['experimental_native_seconds'],candidate_seconds=b['experimental_native_seconds'],
        background_prefetch_drain_seconds=prefetch_wait,
        time_reduction=reduction,activated=False,
        limits='One same-input full-frame4→8 pair following eight tile controls; not a long-run performance guarantee. '
            'DEFLATE6 unchanged. Candidate TIFFs disposed after validation; metrics retained, no permanent cache added.')
    if no_growth and reduction>=.03:
        if profile_path.read_text()!=original:raise RuntimeError('Concurrent profile mutation; do not overwrite')
        if any(t['execution']['compute_admission']['spilled_bytes'] for m in measurements for t in m['comparisons']):
            raise RuntimeError('No-growth candidate spilled; keep original profile')
        save(out/'prior_profile.json',profile)
        decision['activated']=True
        save(out/'decision.json',decision)
        profile.update(gdal_threads=8,encoding_threads8_pixel_parity_qualified=True,
            encoding_threads8_qualification=str((out/'decision.json').relative_to(p)),
            encoding_threads8_qualification_sha256=sha(out/'decision.json'))
        save(profile_path,profile)
    else:save(out/'decision.json',decision)
    print(json.dumps(decision),flush=True)


if __name__=='__main__':main()
