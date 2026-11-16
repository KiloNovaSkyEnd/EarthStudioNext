"""One bounded worker experiment, isolated from native production at a scan boundary."""
from datetime import datetime,timedelta,timezone
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges.earth_validation.project import save
from ges_next.isolation import require_writable


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['workers','encoding','no-growth','full-no-growth'],default='workers')
    args=parser.parse_args()
    p=require_writable(ROOT/'data/projects/H9_20261020_UTCminus7_1100_1700')
    reports=p/'reports'
    current=json.loads((reports/'status.json').read_text())
    target=(datetime.fromisoformat(current['utc'].replace('Z','+00:00'))+timedelta(minutes=10)).isoformat().replace('+00:00','Z')
    now=datetime.now(timezone.utc);token=uuid.uuid4().hex
    control=reports/'performance_window.json'
    if control.exists():
        previous=json.loads(control.read_text())
        if previous.get('state')=='hold' and datetime.fromisoformat(previous['expires_utc'])>now:
            raise RuntimeError('Another active research window owns the boundary')
    state=dict(state='hold',utc=target,created_utc=now.isoformat(),expires_utc=(now+timedelta(minutes=20)).isoformat(),token=token)
    save(control,state)
    record=dict(state='waiting_for_boundary',utc=target,token=token,created_utc=now.isoformat())
    audit=reports/f'{args.mode}_isolated_window_20261023.json'
    save(audit,record);print(json.dumps(record),flush=True)
    window_deadline=time.monotonic()+1140
    try:
        deadline=time.monotonic()+600
        while True:
            status=reports/'performance_window_status.json'
            if status.exists() and json.loads(status.read_text()).get('token')==token:break
            if time.monotonic()>deadline:raise TimeoutError('Boundary window not reached within10 minutes')
            time.sleep(2)
        record['state']='benchmark_running';save(audit,record)
        command=[sys.executable,'-X','utf8','-u',str(ROOT/'scripts/benchmark_h9_chunks.py'),
            '--project',str(p),'--output',str(reports/'workers_isolated_research_20261023'),
            '--runs','1024x6s,1024x8s,1024x4s,1024x4s,1024x8s,1024x6s']
        if args.mode=='encoding':
            command=[sys.executable,'-X','utf8','-u',str(ROOT/'scripts/qualify_h9_fast_deflate.py')]
        if args.mode=='no-growth':
            command=[sys.executable,'-X','utf8','-u',str(ROOT/'scripts/benchmark_h9_chunks.py'),
                '--project',str(p),'--output',str(reports/'no_growth_controls_20261023'),
                '--runs','1024x6s,1024x6s,2048x6s,2048x4s,2048x4s,2048x6s,1024x6s,1024x6s',
                '--gdal-thread-runs','4,8,4,4,4,4,8,4',
                '--decoded-directory',str(reports/'workers_shared_research_20261023/private_decoded_o3wd4x_z'),
                '--discard-candidate-tiffs']
        if args.mode=='full-no-growth':
            command=[sys.executable,'-X','utf8','-u',str(ROOT/'scripts/qualify_h9_no_growth_threads.py')]
        # Own the experiment subtree, including full-scan row processes. Stop
        # that subtree on timeout before finally releasing native production.
        with (reports/f'{args.mode}_isolated_research_20261023.log').open('w',encoding='utf-8') as stream:
            child=subprocess.Popen(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
            try:
                returncode=child.wait(timeout=min(800 if args.mode=='full-no-growth' else 540,
                    max(1,window_deadline-time.monotonic())))
            except BaseException:
                # The full scan launches row children. Kill the owned experiment
                # tree before allowing production to continue after a timeout.
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],
                    stdout=stream,stderr=subprocess.STDOUT,check=False)
                child.wait(timeout=15)
                raise
            result=subprocess.CompletedProcess(command,returncode)
        record.update(state='benchmark_finished',returncode=result.returncode)
    except Exception as error:
        record.update(state='benchmark_failed',error=str(error))
        raise
    finally:
        if json.loads(control.read_text()).get('token')==token:
            state.update(state='released',released_utc=datetime.now(timezone.utc).isoformat())
            save(control,state)
        record['released_utc']=datetime.now(timezone.utc).isoformat();save(audit,record)
        print(json.dumps(record),flush=True)


if __name__=='__main__':main()
