"""Reuse local fixed-input recommendations only for the matching host/profile/engine."""
import json,os,platform,shutil,subprocess
from pathlib import Path
import psutil
from ges_next.production.assets import digest

ROOT=Path(__file__).resolve().parents[2]

def host_identity():
    gpu=None;executable=shutil.which('nvidia-smi')
    if executable:
        try:
            result=subprocess.run([executable,'--query-gpu=name,driver_version','--format=csv,noheader'],
                capture_output=True,text=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode==0:gpu=result.stdout.strip()
        except (OSError,subprocess.TimeoutExpired):pass
    return dict(node=platform.node(),logical=os.cpu_count(),physical=psutil.cpu_count(logical=False),processor=platform.processor(),gpu=gpu)

def load(profile):
    if profile is None:return {}
    optional=profile.get('NightMode') in ('ai-vis','ai-vis-ir')
    file=ROOT/('resources/performance/h9_ai_11k_throughput.json' if optional else 'resources/performance/h9_11k_throughput.json')
    try:
        data=json.loads(file.read_text(encoding='utf-8'))
        margin=data.get('science_margin',1.25)
        if type(margin) not in (int,float) or not 1.15<=margin<=1.5:return {}
        if type(data.get('recommended_max_compute')) is not int or not 1<=data['recommended_max_compute']<=8:return {}
        if data['host']!=host_identity():return {}
        if optional:
            slot=data.get('gpu_slot',{})
            runtime=json.loads((ROOT/'resources/models/aivis/runtime.json').read_text(encoding='utf-8'))
            actual=os.environ.get('EARTHSTUDIO_AIVIS_PYTHON',runtime.get('python',''))
            if not data.get('ai_gpu_slot_verified') or profile['NightMode'] not in data.get('night_modes',[]):return {}
            if os.path.normcase(os.path.abspath(actual))!=os.path.normcase(os.path.abspath(slot['executable'])):return {}
            if any(not Path(name).is_file() or digest(Path(name))!=sha for name,sha in slot['files'].items()):return {}
        if any(profile.get(key)!=value for key,value in data['profile'].items()):return {}
        if not data.get('all_assets_identical') or not data.get('independent_reopen_verified'):return {}
        if any(digest(ROOT/name)!=sha for name,sha in data['engine'].items()):return {}
        return data
    except (OSError,ValueError,KeyError):return {}
