"""Bounded download/compute overlap, independent ownership and per-scan commit gates."""
import json,time,queue,threading,traceback
from contextlib import ExitStack
from collections import deque
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from datetime import datetime,timezone
from pathlib import Path
from . import runner
from .admission import capacity,MAX_SCANS
from .concurrency import Concurrency
from .locking import exclusive,QueueBusyError
from .transfer import acquire
from .network_retry import DownloadCancelled
from .scan_task import process
from .retry_book import RetryBook,enabled as unattended_enabled
from ges_next.production.assets import write_json
from ges_next.production.profile import h9_profile


def take_pending(pending,root,plan,recovery_busy,fresh_available=True):
    """One committed-frame recovery may overlap fresh scientific work."""
    if not recovery_busy:
        for step in pending:
            if (runner.package_for(root,step['utc'],plan)/'commit.json').exists():
                pending.remove(step);return step
    if fresh_available:
        for step in pending:
            if not (runner.package_for(root,step['utc'],plan)/'commit.json').exists():
                pending.remove(step);return step
    return None


def take_ready(ready,recovery_busy,science_available):
    """Recover one committed frame even while the science target is full."""
    if not recovery_busy:
        for row in ready:
            if (row[1]/'commit.json').exists():
                ready.remove(row);return row
    if science_available:
        for row in ready:
            if not (row[1]/'commit.json').exists():
                ready.remove(row);return row
    return None


def run(root,client,workers,cache_root=None,allow_missing=False,report=lambda v:None,max_compute=3,prefetch=3):
    try:return _run(root,client,workers,cache_root,allow_missing,report,max_compute,prefetch)
    except Exception as error:
        # A second launcher does not own the queue and must never mark the
        # healthy owner's state as failed or overwrite its diagnostics.
        if isinstance(error,QueueBusyError) and error.path==(Path(root)/'queue.lock').resolve():raise
        file=Path(root)/'state.json'
        if file.exists():
            value=json.loads(file.read_text(encoding='utf-8'))
            if value.get('phase')!='failed-inputs-preserved':
                failure=dict(occurred_utc=datetime.now(timezone.utc).isoformat(),stage=value.get('phase'),
                    error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
                write_json(Path(root)/'last_failure.json',failure)
                value.update(phase='failed-inputs-preserved',error=str(error));write_json(file,value);report(value)
        raise


def _run(root,client,workers,cache_root,allow_missing,report,max_compute,prefetch):
    root,plan,state=runner.load(root)
    # New profiles still require one independently reopened sample and human acceptance.
    if not runner.accepted(root,state):
        return runner.run(root,client,workers,cache_root,allow_missing,report)
    profile=plan['project']['Production'];signals=queue.SimpleQueue();verification=threading.Lock()
    downloads={};computations={};ready=deque();active={};failed=[];stopping=False;began=time.time()
    shutdown=threading.Event();last_heartbeat=0;recovery_jobs=set()
    def pause_requested():
        file=root/'pause_requested.json'
        return file.exists() and file.stat().st_mtime>=began
    order={s['utc']:i for i,s in enumerate(plan['steps'])}
    retry_book=RetryBook(root,order,unattended_enabled(root));deferred={};retry_inflight=set()
    def save(phase,**extra):
        state.pop('error',None);state.pop('error_stage',None)
        if plan.get('control_revision'):
            from .queue_changes import summary
            state.update(plan=summary(plan),control_revision=plan['control_revision'],excluded_utc=plan.get('excluded_utc',[]))
        state.update(phase=phase,updated_utc=datetime.now(timezone.utc).isoformat(),active=list(active.values()),**extra)
        if retry_book.active:state['unattended']=dict(enabled=True,retrying=len(retry_book.rows),requires_attention=sum(bool(r['requires_attention']) for r in retry_book.rows.values()))
        write_json(root/'state.json',state)
        with (root/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(utc=state['updated_utc'],phase=phase,completed=len(state['completed']),active=state['active']),ensure_ascii=False)+'\n')
        report(state.copy())
    with exclusive(root/'queue.lock'):
        root,plan,state=runner.load(root)
        if plan['missing_nodes'] and not allow_missing:
            save('awaiting-missing-decision',missing_nodes=plan['missing_nodes']);return state
        slots=max(1,capacity(root,plan,max_compute))
        if state.get('error'):state['last_error']=dict(message=state['error'],resumed_utc=datetime.now(timezone.utc).isoformat())
        state.pop('pause_reason',None)
        save('checking-completed',checked_completed=0)
        remaining=[]
        checked=0
        with ExitStack() as checks:
            for step in plan['steps']:
                if pause_requested():save('paused-user');return state
                utc=step['utc'];package=runner.package_for(root,utc,plan)
                if utc in state['completed']:
                    if checked%25==0:
                        # Shared anchor/template bytes need one hash only while
                        # read handles prevent mutation. Bound open handles to
                        # a small batch; every frame still passes its own gate.
                        from ges_next.production.validation_session import ValidationSession
                        checks.close();checks.enter_context(ValidationSession())
                    if utc in plan.get('reused_packages',{}):
                        from .extension import verified_reference
                        verified_reference(package,utc,plan['reused_packages'][utc]['commit_sha256'])
                    else:
                        journal=runner.journal_for(package)
                        try:
                            row=journal.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()
                            journal.gate(row['id'],utc)
                        finally:journal.close()
                    checked+=1;report(dict(phase='checking-completed',checked_completed=checked,completed_count=len(state['completed'])))
                    if checked%25==0:save('checking-completed',checked_completed=checked)
                elif utc not in set(plan.get('excluded_utc',[])):remaining.append(step)
        for utc in list(retry_book.rows):
            if utc in state['completed']:retry_book.complete(utc)
        governor=Concurrency(root,max_compute,prefetch,profile)
        pending=deque()
        for step in remaining:
            if step['utc'] in retry_book.rows:
                deferred[step['utc']]=step;active[step['utc']]=retry_book.describe(step['utc'])
            else:pending.append(step)
        save('parallel-running',compute_slots=slots,prefetch_limit=prefetch)
        def prepare(step,package):
            signals.put(('stage',step['utc'],'acquiring'))
            if not (package/'commit.json').exists():
                acquire(step,package,cache_root,client,lambda detail:signals.put(('progress',step['utc'],detail)),
                    cancelled=lambda:shutdown.is_set() or pause_requested())
            return step,package
        def tasks():
            return [dict(package=p,phase=active.get(s['utc'],{}).get('phase','producing'),
                threads=active.get(s['utc'],{}).get('threads',0)) for s,p,_ in computations.values()]
        def science_count():return sum(t['phase']=='producing' for t in tasks())
        def computation_capacity():
            # Finished science waiting for verification must not take
            # the extra slot needed to replenish the chosen floor.
            # Keep a bounded executor/backlog; never count queued
            # work as an unbounded stream of running science.
            return MAX_SCANS+1 if governor.minimum_science() else slots+1
        with ThreadPoolExecutor(max_workers=2) as net,ThreadPoolExecutor(max_workers=MAX_SCANS+1) as cpu:
            change_file=root/'queue_changes.json';change_stamp=None
            while pending or downloads or computations or ready or deferred:
                stamp=change_file.stat().st_mtime_ns if change_file.exists() else None
                if stamp!=change_stamp:
                    from .queue_changes import refresh
                    plan,changed=refresh(root,plan,pending,deferred,active,retry_book,retry_inflight,set(state['completed']))
                    change_stamp=stamp
                    if changed:
                        order={s['utc']:i for i,s in enumerate(plan['steps'])};save('parallel-running')
                if pause_requested():stopping=True;shutdown.set()
                waiting_reason=None
                if not stopping:
                    for utc in retry_book.due():
                        if utc not in deferred or utc in retry_inflight:continue
                        step=deferred.pop(utc);retry_inflight.add(utc)
                        # Re-enter normal acquisition and ownership checks. A commit
                        # is reused by prepare/process; accepted JPG is not remade.
                        pending.appendleft(step)
                        active[utc]=dict(utc=utc,phase='waiting-download')
                if governor.refresh(tasks(),bool(ready)):
                    slots=governor.target;prefetch=governor.prefetch
                    save('parallel-running',compute_slots=slots,prefetch_limit=prefetch,concurrency=governor.details())
                while not stopping and ready and len(computations)<computation_capacity():
                    recovery_ready=not recovery_jobs and any((row[1]/'commit.json').exists() for row in ready)
                    science_available=science_count()<slots
                    if not recovery_ready and not science_available:break
                    if not recovery_ready and not governor.admit(tasks()):
                        waiting_reason='memory'
                        break
                    candidate=take_ready(ready,bool(recovery_jobs),science_available)
                    if candidate is None:break
                    step,package,job=candidate;utc=step['utc']
                    reused=(package/'commit.json').exists()
                    if reused:recovery_jobs.add(utc)
                    active[utc]=dict(utc=utc,phase='waiting-verification' if reused else 'producing',threads=governor.thread_count())
                    progress=lambda phase,u=utc:signals.put(('stage',u,phase))
                    local=workers.fork(lambda value,u=utc:signals.put(('progress',u,value)),max(2,science_count()+1)) if hasattr(workers,'fork') else workers
                    if hasattr(local,'environment'):local.environment.update(governor.worker_environment())
                    future=cpu.submit(process,step,package,job,profile,local,verification,root,state,progress)
                    computations[future]=(step,package,job)
                while not stopping and pending:
                    # Committed recovery transfers no payload and must not be
                    # blocked by a full fresh-data prefetch buffer.
                    recovery_busy=bool(recovery_jobs) or any((p/'commit.json').exists() for _,p,_ in list(downloads.values())+list(ready))
                    fresh_available=len(downloads)+len(ready)<prefetch
                    step=take_pending(pending,root,plan,recovery_busy,fresh_available)
                    if step is None:break
                    package=runner.package_for(root,step['utc'],plan)
                    if not (package/'commit.json').exists() and capacity(root,plan,1)==0:
                        pending.appendleft(step);waiting_reason='space';break
                    journal=runner.journal_for(package)
                    try:job=journal.create_job(package,runner.h9_profile(profile['JpegQuality'],profile['NightLightMetres'],**({'night_mode':profile['NightMode']} if profile.get('NightMode') else {})),
                        keep_l1=profile.get('KeepL1',False),keep_intermediates=profile.get('KeepIntermediates',False))
                    finally:journal.close()
                    active[step['utc']]=dict(utc=step['utc'],phase='waiting-download')
                    future=net.submit(prepare,step,package);downloads[future]=(step,package,job)
                    save('parallel-running')
                dirty=False
                while not signals.empty():
                    kind,utc,value=signals.get()
                    if utc in state['completed']:continue
                    if kind=='stage':active.setdefault(utc,dict(utc=utc))['phase']=value;dirty=True
                    else:
                        detail_phase=value.get('phase') if isinstance(value,dict) else None
                        if detail_phase in ('download-retrying','download-recovered'):
                            scan=active.setdefault(utc,dict(utc=utc))
                            waits=scan.setdefault('network_waits',{})
                            if detail_phase=='download-retrying':
                                waits[value['key']]=value
                            else:
                                waits.pop(value['key'],None)
                            if waits:scan.update(phase='waiting-network',retry=next(iter(waits.values())))
                            else:scan.update(phase='acquiring');scan.pop('retry',None)
                            dirty=True
                        report(dict(phase='parallel-progress',utc=utc,detail=value,completed_count=len(state['completed']),active=list(active.values())))
                if state.get('waiting_reason')!=waiting_reason:
                    state['waiting_reason']=waiting_reason;dirty=True
                if time.monotonic()-last_heartbeat>=10:
                    last_heartbeat=time.monotonic();dirty=True
                if dirty:save('parallel-running')
                futures=list(downloads)+list(computations)
                if futures:done=wait(futures,timeout=.25,return_when=FIRST_COMPLETED).done
                else:time.sleep(.25);done=set()
                for future in done:
                    downloading=future in downloads
                    step,package,job=(downloads if downloading else computations).pop(future);utc=step['utc']
                    if not downloading:recovery_jobs.discard(utc)
                    try:
                        result=future.result()
                        if downloading:
                            ready.append((step,package,job));active[utc]=dict(utc=utc,phase='ready')
                        else:
                            governor.sample_completed(package)
                            state['completed'].append(utc);state['completed'].sort(key=order.get)
                            retry_book.complete(utc);retry_inflight.discard(utc)
                            active.pop(utc,None);state['utc']=utc;state['cleaned_files']=result['cleaned_files']
                        save('parallel-running')
                    except DownloadCancelled:
                        # Only explicit pause or another fatal task cancels network waits.
                        active[utc]=dict(utc=utc,phase='waiting-download');stopping=True;shutdown.set()
                    except Exception as error:
                        failure=dict(utc=utc,stage=active.get(utc,{}).get('phase'),error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
                        if retry_book.active:
                            active[utc]=retry_book.defer(step,failure,downloading)
                            deferred[utc]=step;retry_inflight.discard(utc)
                            report(dict(phase='frame-retry-scheduled',**active[utc]['retry'],utc=utc))
                        else:
                            failed.append(failure);active[utc]=dict(utc=utc,phase='failed');stopping=True;shutdown.set()
                        write_json(root/'last_failure.json',dict(occurred_utc=datetime.now(timezone.utc).isoformat(),**failure))
                if stopping and not downloads and not computations:break
                if not futures and not ready and not pending and not deferred:break
        if failed:
            save('failed-inputs-preserved',error=failed[0]['error'],error_stage=failed[0]['stage'],utc=failed[0]['utc'],failures=failed)
            raise RuntimeError(failed[0]['error'])
        if stopping:
            save({'space':'paused-space','memory':'paused-resources'}.get(state.get('pause_reason'),'paused-user'));return state
        active.clear()
        write_json(root/'sequence_index.json',dict(schema='earthstudio.layered_sequence.v1',nodes=plan['nodes'],
            frames=[dict(utc=s['utc'],commit=str(runner.package_for(root,s['utc'],plan)/'commit.json')) for s in plan['steps'] if s['utc'] in state['completed']]))
        save('complete');return state
