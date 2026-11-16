"""Append-only queue revisions. Old accepted scans stay read-only and are never re-owned."""
import json
from pathlib import Path
from .locking import exclusive
from .runner import load,package_for,journal_for
from ges_next.production.assets import digest,verify_assets,write_json


def verified_reference(package,utc,commit_hash=None):
    package=Path(package).resolve()
    if commit_hash and digest(package/'commit.json')!=commit_hash:raise ValueError('Reused scan commit changed')
    journal=journal_for(package)
    try:
        row=journal.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()
        if row is None:raise ValueError('Reused scan has no verified owner')
        journal.gate(row['id'],utc)
    finally:journal.close()
    return dict(package=str(package),commit_sha256=digest(package/'commit.json'))


def inherit(previous,project,steps):
    previous,old,state=load(previous,verify_runtime=False)
    with exclusive(previous/'queue.lock'):
        previous,old,state=load(previous,verify_runtime=False)
        if state['phase']!='complete':raise ValueError('请先完成或恢复原制作队列，再追加新的时间段')
        frozen=old['project']
        for key in ('Id','StartUtc','IntervalMinutes','SatelliteSelection','Production','Scope','Recipe','DataDirectory'):
            if frozen.get(key)!=project.get(key):raise ValueError('追加必须保持项目、起点、卫星、配方及制作档位一致')
        if frozen.get('CaptureMode','sequence')!='sequence' or project.get('CaptureMode','sequence')!='sequence':raise ValueError('仅序列项目可以追加')
        from ges_next.selection import utc
        if utc(project['EndUtc'])<=utc(frozen['EndUtc']):raise ValueError('追加结束时间应晚于原队列结束时间')
        old_steps={s['utc']:s for s in old['steps']};new_steps={s['utc']:s for s in steps}
        references={}
        for stamp in state['completed']:
            if stamp not in new_steps or old_steps[stamp]['objects']!=new_steps[stamp]['objects']:
                raise ValueError('已完成扫描的目录身份变化；请先核对，不自动覆盖旧成果')
            references[stamp]=verified_reference(package_for(previous,stamp),stamp)
        return dict(queue=str(previous),plan_sha256=digest(previous/'plan.json')),references


def reuse_completed(previous,project,steps):
    """Read-only intersection with a completed queue, independent of project dates/id."""
    previous,old,state=load(previous,verify_runtime=False)
    with exclusive(previous/'queue.lock'):
        previous,old,state=load(previous,verify_runtime=False)
        if state['phase']!='complete':raise ValueError('跨项目复用需要选择已完成的源队列')
        frozen=old['project']
        for key,default in (('IntervalMinutes',None),('SatelliteSelection',None),('Production',None),('Scope','global-nonpolar'),('Recipe','geocolor-style'),('CaptureMode','sequence')):
            if (frozen.get(key) if frozen.get(key) is not None else default)!=(project.get(key) if project.get(key) is not None else default):
                raise ValueError('跨项目复用要求卫星、采样、配方和制作档位一致：'+key)
        lookup={s['utc']:s for s in old['steps']}
        completed=set(state['completed']);references={}
        for step in steps:
            stamp=step['utc']
            if stamp not in completed:continue
            if stamp not in lookup or lookup[stamp]['objects']!=step['objects']:
                raise ValueError('重叠时次的目录身份变化，不能复用：'+stamp)
            inherited=old.get('reused_packages',{}).get(stamp,{})
            references[stamp]=verified_reference(package_for(previous,stamp,old),stamp,inherited.get('commit_sha256'))
        if not references:raise ValueError('所选已完成项目与当前范围没有可复用的精确时次')
        return dict(queue=str(previous),plan_sha256=digest(previous/'plan.json'),kind='cross-project'),references
