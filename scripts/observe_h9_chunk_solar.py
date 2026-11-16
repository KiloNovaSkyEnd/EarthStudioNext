"""Bounded verification of actual tuned native children and committed pixels."""
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
    except (FileNotFoundError,PermissionError,ValueError):return {}


def main():
    project=ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700'
    target=project/'reports/chunk_solar_activation.json'
    began=time.monotonic()
    while time.monotonic()-began<1200:
        proof=read(target)
        if not proof:
            time.sleep(2);continue
        status=read(project/'reports/status.json')
        utc=status.get('utc')
        if not utc:
            time.sleep(2);continue
        folder=project/'processed'/datetime.fromisoformat(utc.replace('Z','+00:00')).strftime('%Y%m%dT%H%MZ')
        verified=[]
        for receipt in sorted(folder.glob('native_*.json')):
            tile=read(receipt);execution=tile.get('execution',{})
            if not (execution.get('compute_chunk')==1024 and execution.get('shared_solar_factors')
                    and execution.get('solar_factor_execution',{}).get('cos_calls',0)>0
                    and execution.get('gpu_calls',0)>0):continue
            with receipt.with_suffix('.tif').open('rb') as stream:
                actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=tile['sha256']:raise ValueError('Committed tuned production TIFF differs from its hash')
            verified.append(dict(receipt=str(receipt.relative_to(project)),sha256_verified=True,execution=execution))
            if len(verified)>=2:break
        if len(verified)>=2:
            work=[]
            for root in sorted(folder.glob('work*')):
                config=read(root/'project.json')
                if config.get('shared_solar_factors'):
                    work.append(dict(config=config,resources=read(root/'reports/resource_usage.json'),
                        progress=read(root/'reports/compute_progress.json')))
            proof.update(stage='actual_production_chunk1024_shared_solar_and_cuda_verified',
                observed_utc=datetime.now(timezone.utc).isoformat(),actual_science_status=status,
                actual_tuned_work=work,verified_committed_tiles=verified,
                limits='Actual tuned rows and two committed TIFF hashes verified. Transition scan not a speed control; '
                'end-to-end tuned sequence benefit still requires later production timing.')
            save(target,proof)
            print('ACTUAL_CHUNK_SOLAR_PRODUCTION_VERIFIED',utc,len(verified),flush=True)
            return
        time.sleep(2)
    raise TimeoutError('Tuned activation observation timed out; production left untouched')


if __name__=='__main__':main()
