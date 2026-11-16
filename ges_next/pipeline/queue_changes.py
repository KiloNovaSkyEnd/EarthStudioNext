"""Live scheduling revisions; frozen base, accepted outputs and active work stay owned."""
import json
from datetime import datetime,timezone
from pathlib import Path
from .locking import exclusive
from .plan import signature
from ges_next.production.assets import digest,write_json

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def compatible(base,project):
    from ges_next.selection import utc
    for key,value in signature(base).items():
        if key!='EndUtc' and value!=signature(project).get(key):
            raise ValueError('运行中只能调整时间范围，不能更换起点、卫星、画质、配方或存储位置：'+key)
    if utc(project['EndUtc'])<utc(base['EndUtc']):raise ValueError('缩减范围请取消未开始时次；不要回写原计划')

def effective(root,base):
    path=Path(root)/'queue_changes.json'
    if not path.exists():return base
    change=read(path)
    if change.get('schema')!='earthstudio.queue_changes.v1' or change['base_plan_sha256']!=digest(Path(root)/'plan.json'):
        raise ValueError('队列变更不属于原冻结计划')
    compatible(base['project'],change['project'])
    if change['runtime']!=base['runtime']:raise ValueError('变更不能替换科学代码身份')
    steps={s['utc']:s for s in base['steps']}
    for step in change['added_steps']:
        if step['utc'] in steps:raise ValueError('新增时次与原计划重复')
        steps[step['utc']]=step
    if set(change['excluded_utc'])-set(steps):raise ValueError('取消时次不属于队列')
    result=dict(base,project=change['project'],steps=[steps[k] for k in sorted(steps)],nodes=change['nodes'],
        requested_nodes=len(change['nodes']),missing_nodes=sum(n['state'] not in ('catalog_available','user-excluded') for n in change['nodes']),
        control_revision=change['revision'],excluded_utc=change['excluded_utc'])
    result['_base_project']=base['project']
    largest=max(sum(o['bytes'] for o in s['objects']) for s in result['steps'])
    result['largest_scan_bytes']=max(base['largest_scan_bytes'],largest)
    result['minimum_start_free_bytes']=max(base['minimum_start_free_bytes'],largest+(18 if base['project']['Production']['NightLightMetres']==500 else 14)*1024**3)
    result['download_bytes']=sum(sum(o['bytes'] for o in s['objects']) for s in result['steps'] if s['utc'] not in set(change['excluded_utc']))
    result['estimated_final_bytes']=round(base['estimated_final_bytes']*len([s for s in result['steps'] if s['utc'] not in set(change['excluded_utc'])])/len(base['steps']))
    return result

def summary(plan):
    """Existing native client can display this bounded plan without imagery object lists."""
    excluded=set(plan.get('excluded_utc',[]))
    return {**{k:plan[k] for k in ('project','missing_nodes','download_bytes','estimated_final_bytes','minimum_start_free_bytes')},'control_revision':plan.get('control_revision',0),
        'steps':[{'utc':s['utc']} for s in plan['steps'] if s['utc'] not in excluded]}

def stage(root,candidate=None,cancel_start=None,cancel_end=None):
    from ges_next.selection import utc
    root=Path(root)
    with exclusive(root/'queue_changes.lock'):
        base=read(root/'plan.json');current=effective(root,base);state=read(root/'state.json')
        completed=set(state['completed']);active={s['utc'] for s in state.get('active',[]) if s.get('phase')!='retry-wait'}
        if candidate is not None:
            compatible(base['project'],candidate['project'])
            if utc(candidate['project']['EndUtc'])<utc(current['project']['EndUtc']):
                raise ValueError('新检查范围不能缩短已加入队列的范围；缩减请取消未开始时次')
            if candidate['runtime']!=base['runtime']:
                from .plan import runtime_signature
                from ges_next.performance.compatibility import permits
                if candidate['runtime']!=runtime_signature() or not permits(base['runtime'],candidate['runtime'],base['project']['Production']):
                    raise ValueError('科学代码身份不匹配，也没有既有资格证明')
            # A refreshed catalog can be temporarily incomplete. Keep prior exact
            # identities; a search result must never discard already queued work.
            offered={s['utc']:s for s in candidate['steps']}
            for s in current['steps']:
                if s['utc'] in offered and offered[s['utc']]!=s:raise ValueError('目录改变已有时次身份：'+s['utc'])
            prior={s['utc']:s for s in current['steps']};retained=sorted(set(prior)-set(offered));prior.update(offered)
            current=dict(current,project=candidate['project'],steps=[prior[k] for k in sorted(prior)],
                nodes=[dict(n,state='catalog_available') if n['utc'] in prior else n for n in candidate['nodes']],retained_existing_utc=retained)
        excluded=set(current.get('excluded_utc',[]));protected=[]
        if cancel_start is not None or cancel_end is not None:
            if cancel_start is None or cancel_end is None or utc(cancel_start)>utc(cancel_end):raise ValueError('请输入完整且递增的取消UTC范围')
            for s in current['steps']:
                stamp=s['utc']
                if utc(cancel_start)<=utc(stamp)<=utc(cancel_end):
                    if stamp in completed or stamp in active:protected.append(stamp)
                    else:excluded.add(stamp)
        base_times={s['utc'] for s in base['steps']}
        change=dict(schema='earthstudio.queue_changes.v1',base_plan_sha256=digest(root/'plan.json'),
            revision=current.get('control_revision',0)+1,updated_utc=datetime.now(timezone.utc).isoformat(),
            project=current['project'],runtime=base['runtime'],added_steps=[s for s in current['steps'] if s['utc'] not in base_times],
            nodes=[dict(n,state='user-excluded') if n['utc'] in excluded else n for n in current['nodes']],excluded_utc=sorted(excluded),retained_existing_utc=current.get('retained_existing_utc',[]))
        # One atomic manifest is the commit point; never write the running state/plan/acceptance here.
        write_json(root/'queue_changes.json',change)
        write_json(root/'effective_plan_summary.json',summary(effective(root,base)))
        # Guardian continuation validates this snapshot. Keep it aligned with a
        # new end time, otherwise a later crash could reject the stale request.
        request_path=root/'current_request.earthproj'
        if candidate is not None and request_path.is_file():
            request=read(request_path);request.update(change['project']);write_json(request_path,request)
        return dict(revision=change['revision'],total=len(current['steps']),added=len(change['added_steps']),excluded=len(excluded),protected=protected)

def refresh(root,plan,pending,deferred,active,retry_book,retry_inflight,completed):
    """Called only by the queue owner, at a scheduler boundary."""
    latest=effective(root,read(Path(root)/'plan.json'))
    if latest.get('control_revision',0)==plan.get('control_revision',0):return plan,False
    # The persisted UI snapshot can lag actual launches. The owner arbitrates at
    # this boundary, so a cancellation racing with a launch cannot hide that scan.
    protected=set(completed)|{stamp for stamp,task in active.items() if task.get('phase')!='retry-wait'}
    if protected.intersection(latest.get('excluded_utc',[])):
        with exclusive(Path(root)/'queue_changes.lock'):
            path=Path(root)/'queue_changes.json';change=read(path)
            retained=protected.intersection(change['excluded_utc'])
            change['excluded_utc']=[stamp for stamp in change['excluded_utc'] if stamp not in retained]
            change['nodes']=[dict(n,state='catalog_available') if n['utc'] in retained else n for n in change['nodes']]
            change['revision']+=1;change['protected_at_owner_boundary']=sorted(retained)
            write_json(path,change)
            latest=effective(root,read(Path(root)/'plan.json'))
            write_json(Path(root)/'effective_plan_summary.json',summary(latest))
    excluded=set(latest.get('excluded_utc',[]))
    removed=[s['utc'] for s in pending if s['utc'] in excluded]
    kept=[s for s in pending if s['utc'] not in excluded];pending.clear();pending.extend(kept)
    for stamp in removed:
        active.pop(stamp,None);retry_book.complete(stamp);retry_inflight.discard(stamp)
    for stamp in list(deferred):
        if stamp in excluded:
            deferred.pop(stamp);active.pop(stamp,None);retry_book.complete(stamp);retry_inflight.discard(stamp)
    known={s['utc'] for s in plan['steps']}
    for step in latest['steps']:
        if step['utc'] not in known and step['utc'] not in excluded and step['utc'] not in completed:
            pending.append(step);retry_book.known.add(step['utc'])
    return latest,True

def live_append(project,inventory,output,previous):
    """Compatibility for M13's plan-and-attach call: an alias, never a second owner.

    The client always attaches its requested output directory after a plan call.
    A junction lets that existing client keep following the exact original queue.
    All Python ownership paths resolve to the canonical queue before execution.
    """
    import os,uuid
    from .plan import create
    from ges_next.isolation import require_writable
    root=require_writable(previous);output=require_writable(output)
    if output.exists():raise FileExistsError('追加连接目录必须不存在')
    candidate_root=root/'change_candidates'/uuid.uuid4().hex
    candidate=create(project,inventory,candidate_root)
    # Validate all identity constraints before making a visible native attachment.
    compatible(read(root/'plan.json')['project'],candidate['project'])
    output.parent.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        import _winapi
        _winapi.CreateJunction(str(root),str(output))
    else:output.symlink_to(root,target_is_directory=True)
    try:
        receipt=stage(root,candidate)
    except Exception:
        # Only remove our just-created alias, never its resolved queue contents.
        if output.resolve()==root:
            if os.name=='nt':os.rmdir(output)
            else:output.unlink()
        raise
    write_json(candidate_root/'applied.json',dict(**receipt,canonical_queue=str(root),native_attachment=str(output),attachment_kind='directory-alias-not-new-production'))
    return summary(effective(root,read(root/'plan.json')))

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--cancel-start',required=True);parser.add_argument('--cancel-end',required=True)
    args=parser.parse_args()
    try:print(json.dumps(dict(phase='queue-revised',**stage(args.queue,cancel_start=args.cancel_start,cancel_end=args.cancel_end)),ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(phase='error',error=str(error)),ensure_ascii=False));raise SystemExit(1)

if __name__=='__main__':main()
