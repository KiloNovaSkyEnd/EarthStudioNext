"""Collect only committed scans; unfinished work is never reclassified as missing."""
from datetime import datetime,timedelta
import json
import math
from pathlib import Path
from ges_next.production.assets import digest,verify_assets

ROLES={'base':('stock-clouds-day-without-ground-background','.jpg'),
       'night':('shared-static-night-background','.jpg'),
       'transmission':('stock-ground-transmission','.png'),
       'support':('actual-observation-support','.png')}


def read(package):
    package=Path(package).resolve();data=json.loads((package/'commit.json').read_text(encoding='utf-8'))
    if data.get('schema')!='earthstudio.layered_jpeg.v1':raise ValueError('需要正式JPG分层提交')
    verify_assets(package,data['assets']);verify_assets(package,[data['rebuild_recipe']])
    if len(data['assets'])!=4 or set(a['role'] for a in data['assets'])!={r[0] for r in ROLES.values()}:raise ValueError('分层不完整或重复')
    if not math.isfinite(data['quality']['psnr_db']) or data['quality']['psnr_db']<35:raise ValueError('候选未通过数值筛查')
    from ges_next.production.rebuild_recipe import validate
    recipe=json.loads((package/data['rebuild_recipe']['path']).read_text(encoding='utf-8'));validate(recipe)
    if recipe['utc']!=data['utc'] or not data['utc'].endswith('Z'):raise ValueError('重做清单或UTC身份不一致')
    return dict(package=package,commit=data,utc=data['utc'],commit_sha256=digest(package/'commit.json'))


def collect(packages,step_minutes=10):
    if step_minutes not in (10,15,30,60):raise ValueError('时间步长不受支持')
    rows=sorted([read(p) for p in packages],key=lambda r:r['utc'])
    if not rows or len({r['utc'] for r in rows})!=len(rows):raise ValueError('至少一个时次，UTC不能重复')
    night_recipes={json.dumps(r['commit'].get('night_recipe',{}).get('recipe'),sort_keys=True) for r in rows}
    if len(night_recipes)!=1:raise ValueError('不能在同一序列混用不同夜间配方或模型版本')
    first=rows[0]['commit']['grid'];lookup={r['utc']:r for r in rows}
    if any(any(r['commit']['grid'][k]!=first[k] for k in ('shape','extent','crs')) for r in rows):raise ValueError('序列网格不一致')
    from ges_next.production.night_detail import layer_shape
    for row in rows:
        if any(a['shape']!=layer_shape(row['commit']['grid'],a['role']) or a['shape']!=layer_shape(first,a['role']) for a in row['commit']['assets']):raise ValueError('图层尺寸或夜景档位与序列不一致')
    start=datetime.fromisoformat(rows[0]['utc'].replace('Z','+00:00'));end=datetime.fromisoformat(rows[-1]['utc'].replace('Z','+00:00'))
    count=(end-start).total_seconds()/(step_minutes*60)
    if not count.is_integer() or count>10000:raise ValueError('时间未对齐或过长')
    nodes=[]
    for i in range(int(count)+1):
        utc=(start+timedelta(minutes=i*step_minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')
        nodes.append(dict(index=i+1,utc=utc,missing=utc not in lookup,source=lookup.get(utc)))
    if not set(lookup).issubset({n['utc'] for n in nodes}):raise ValueError('存在未对齐的扫描，不会静默遗漏')
    return nodes,first


def from_queue(queue):
    queue=Path(queue).resolve();plan_path=queue/'plan.json'
    plan=json.loads(plan_path.read_text(encoding='utf-8'));state=json.loads((queue/'state.json').read_text(encoding='utf-8'))
    if digest(plan_path)!=state['plan_sha256']:raise ValueError('队列计划身份已变化')
    from ges_next.pipeline.queue_changes import effective
    plan=effective(queue,plan)
    paths=[]
    for step in plan['steps']:
        from ges_next.pipeline.runner import package_for
        package=package_for(queue,step['utc'],plan)
        if step['utc'] in plan.get('reused_packages',{}):
            from ges_next.pipeline.extension import verified_reference
            verified_reference(package,step['utc'],plan['reused_packages'][step['utc']]['commit_sha256'])
        if (package/'commit.json').exists():paths.append(package)
    nodes,grid=collect(paths,plan['project']['IntervalMinutes'])
    available={s['utc'] for s in plan['steps'] if s['utc'] not in set(plan.get('excluded_utc',[]))}
    if any(n['missing'] and n['utc'] in available for n in nodes):raise ValueError('区间内仍有未完成扫描，不能当成缺档导出')
    return paths,plan['project']['IntervalMinutes']
