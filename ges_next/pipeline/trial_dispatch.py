"""Opt-in routing to a pinned trial runtime. Stable science is not replaced."""
import hashlib,json,os,subprocess,sys
from pathlib import Path

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024**2),b''):h.update(block)
    return h.hexdigest()

def target(queue,formal):
    queue=Path(queue);formal=Path(formal).resolve();file=queue/'performance_trial.json'
    if not file.is_file() or (queue/'performance_trial_result.json').exists():return None
    cfg=read(file)
    if cfg.get('enabled') is not True:return None
    plan=read(queue/'plan.json');profile=plan['project']['Production']
    if profile.get('NightMode')!='ai-vis' or any(profile.get(k)!=v for k,v in
        dict(Format='jpeg',HimawariDiskSize=11000,JpegQuality=95,NightLightMetres=1000).items()):
        raise ValueError('Trial supports only the qualified full AI-VIS 11K profile')
    if cfg.get('duration_seconds')!=7200:raise ValueError('Unqualified trial duration')
    if sha(queue/'plan.json')!=cfg['plan_sha256'] or sha(queue/'quality_acceptance.json')!=cfg['acceptance_sha256']:
        raise ValueError('Frozen plan or human quality approval differs; retain inputs')
    engine=Path(cfg['engine']).resolve();folder=(formal/'resources/runtimes').resolve()
    if not engine.is_relative_to(folder) or engine==folder:raise ValueError('Trial runtime outside managed runtimes')
    manifest=engine/'trial_manifest.json'
    if sha(manifest)!=cfg['manifest_sha256']:raise ValueError('Trial manifest changed')
    for name,expected in read(manifest)['files'].items():
        path=(engine/name).resolve()
        if not path.is_relative_to(engine) or sha(path)!=expected:raise ValueError('Trial source changed: '+name)
    return engine

def dispatch(args):
    if args.action!='run':return
    formal=Path(__file__).resolve().parents[2]
    engine=target(args.queue,formal)
    if engine is None:return
    command=[sys.executable,'-X','utf8','-u','-m','ges_next.pipeline.cli',*sys.argv[1:]]
    result=subprocess.run(command,cwd=engine,env=os.environ.copy())
    raise SystemExit(result.returncode)
