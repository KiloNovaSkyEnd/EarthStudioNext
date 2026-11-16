"""Metadata-only storage preflight: no image copies, decodes or full asset hashing."""
import json,sys,shutil,hashlib
from pathlib import Path
ENGINE=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ENGINE))
from ges_next.pipeline.queue_changes import effective
from ges_next.pipeline.runner import package_for

def estimate(queue):
    queue=Path(queue).resolve();plan=effective(queue,json.loads((queue/'plan.json').read_text(encoding='utf-8')))
    completed=set(json.loads((queue/'state.json').read_text(encoding='utf-8'))['completed']);commits=[];identities={}
    for step in plan['steps']:
        if step['utc'] in completed:
            p=package_for(queue,step['utc'],plan);blob=(p/'commit.json').read_bytes();commits.append(json.loads(blob));identities[step['utc']]=hashlib.sha256(blob).hexdigest()
    if not commits:raise ValueError('No completed observations')
    commits.sort(key=lambda c:c['utc']);from datetime import datetime
    first,last=[datetime.fromisoformat(c['utc'].replace('Z','+00:00')) for c in (commits[0],commits[-1])]
    nodes=int((last-first).total_seconds()/(60*plan['project']['IntervalMinutes']))+1
    night_role='shared-static-night-background';night={a['sha256'] for c in commits for a in c['assets'] if a['role']==night_role};copied=0
    for i,c in enumerate(commits):
        for a in c['assets']:
            if len(night)==1 and i>0 and a['role']==night_role:continue
            copied+=a['bytes']
    reusable=None
    candidates=sorted((queue/'deliveries').glob('*'),key=lambda p:p.stat().st_mtime,reverse=True)
    registration=queue/'editor_workspace.json'
    if registration.is_file():candidates.insert(0,Path(json.loads(registration.read_text(encoding='utf-8'))['path']))
    for folder in candidates:
        try:
            s=json.loads((folder/'sequence_manifest.json').read_text(encoding='utf-8'));m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            if len(s['nodes'])!=nodes or len(s['sources'])!=len(commits):continue
            if [x['utc'] for x in s['sources']]!=[x['utc'] for x in commits]:continue
            if any(x['commit_sha256']!=identities[x['utc']] for x in s['sources']):continue
            if any(s.get('night_recipe')!=c.get('night_recipe',{}).get('recipe') for c in commits):continue
            if len(m['frames'])!=nodes or not all((folder/a['path']).is_file() and (folder/a['path']).stat().st_size==a['bytes'] for a in s['files']+s['auxiliary_files']):continue
            reusable=str(folder);break
        except (OSError,ValueError,KeyError):continue
    data=Path(plan['project']['DataDirectory']);return dict(nodes=nodes,observations=len(commits),copy_bytes=copied,preview_budget_bytes=nodes*16*1024**2+1024**3,free_bytes=shutil.disk_usage(data).free,reusable=reusable)
if __name__=='__main__':print(json.dumps(estimate(sys.argv[1])))
