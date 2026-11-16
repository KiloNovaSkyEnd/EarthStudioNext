"""One scan at a time, independent verification and first-sample quality checkpoint."""
import json
from pathlib import Path
import shutil
from ges_next.production.assets import digest,write_json,verify_assets
from ges_next.production.journal import Journal
from ges_next.production.profile import h9_profile
from ges_next.production.retention import Retention
from .locking import exclusive
from .transfer import acquire
from .network_retry import DownloadCancelled,wait


def load(root,verify_runtime=True):
    from ges_next.isolation import require_writable
    root=require_writable(root)
    plan=json.loads((root/'plan.json').read_text(encoding='utf-8'))
    state=json.loads((root/'state.json').read_text(encoding='utf-8'))
    if state['plan_sha256']!=digest(root/'plan.json'):raise ValueError('队列计划被修改，请重新预检')
    from .plan import runtime_signature
    current_runtime=runtime_signature(plan['project']['Production']) if verify_runtime else None
    if verify_runtime and plan['runtime']!=current_runtime:
        from ges_next.performance.compatibility import permits
        if not permits(plan['runtime'],current_runtime,plan['project']['Production']):raise ValueError('科学或材质代码已变化，请新建候选队列后重新验收档位')
    from .queue_changes import effective
    return root,effective(root,plan),state


def package_for(root,utc,plan=None):
    if plan is None:plan=json.loads((root/'plan.json').read_text(encoding='utf-8'))
    if utc in plan.get('reused_packages',{}):return Path(plan['reused_packages'][utc]['package'])
    return root/'steps'/utc.replace('-','').replace(':','')


def journal_for(package):return Journal(package.parent/'production_journal.sqlite')


def accept_quality(root):
    root,plan,state=load(root)
    with exclusive(root/'queue.lock'):
        root,plan,state=load(root)
        if not state.get('first_sample'):raise ValueError('请先制作并检查首个样本')
        utc=state['first_sample'];package=package_for(root,utc);journal=journal_for(package)
        try:
            row=journal.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()
            journal.verify(row['id'],utc,package/'blender_reopen.json')
            journal.approve_profile(row['id'],user_quality_accepted=True)
            write_json(root/'quality_acceptance.json',dict(plan_sha256=state['plan_sha256'],first_utc=utc,
                first_commit_sha256=digest(package/'commit.json'),human_accepted=True))
        finally:journal.close()


def accepted(root,state):
    receipt=root/'quality_acceptance.json'
    if not receipt.exists():return False
    value=json.loads(receipt.read_text(encoding='utf-8'))
    first=package_for(root,value['first_utc'])/'commit.json'
    return value.get('human_accepted') is True and value['plan_sha256']==state['plan_sha256'] and digest(first)==value['first_commit_sha256']


def run(root,client,workers,cache_root=None,allow_missing=False,report=lambda value:None):
    import time
    began=time.time()
    root,plan,state=load(root);profile=plan['project']['Production']
    def pause_requested():
        file=root/'pause_requested.json'
        return file.exists() and file.stat().st_mtime>=began
    def update(phase,**extra):
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat()
        previous=state.get('phase')
        if phase!='failed-inputs-preserved' and state.get('error'):
            state['last_error']=dict(message=state.pop('error'),phase=state.pop('error_stage',previous),
                occurred_utc=state.get('updated_utc'),resumed_utc=now)
        state.update(phase=phase,updated_utc=now,**extra)
        write_json(root/'state.json',state)
        with (root/'events.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(utc=now,phase=phase,scan_utc=state.get('utc'),completed=len(state['completed']),
                **{k:state[k] for k in ('error','error_stage') if k in state}),ensure_ascii=False)+'\n')
        report(state.copy())
    with exclusive(root/'queue.lock'):
        root,plan,state=load(root)
        if plan['missing_nodes'] and not allow_missing:
            update('awaiting-missing-decision',missing_nodes=plan['missing_nodes']);return state
        try:
            for step in plan['steps']:
                if pause_requested():update('paused-user');return state
                utc=step['utc'];package=package_for(root,utc,plan)
                if utc in plan.get('reused_packages',{}):
                    from .extension import verified_reference
                    verified_reference(package,utc,plan['reused_packages'][utc]['commit_sha256'])
                    report(dict(phase='reusing-accepted-scan',utc=utc));continue
                journal=journal_for(package)
                try:
                    if utc in state['completed']:
                        row=journal.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()
                        journal.gate(row['id'],utc);continue
                    while shutil.disk_usage(root).free < plan['minimum_start_free_bytes'] and not (package/'commit.json').exists():
                        update('waiting-resources',utc=utc,waiting_reason='space')
                        wait(10,time.sleep,pause_requested)
                    state.pop('waiting_reason',None)
                    job=journal.create_job(package,h9_profile(profile['JpegQuality'],profile['NightLightMetres'],**({'night_mode':profile['NightMode']} if profile.get('NightMode') else {})),
                        keep_l1=profile.get('KeepL1',False),keep_intermediates=profile.get('KeepIntermediates',False))
                    if not (package/'commit.json').exists():
                        update('acquiring',utc=utc)
                        acquire(step,package,cache_root,client,lambda detail:report(dict(state,detail=detail)),cancelled=pause_requested)
                        update('producing',utc=utc);workers.produce(step,package,profile)
                    data=json.loads((package/'commit.json').read_text(encoding='utf-8'))
                    if data['utc']!=utc:raise ValueError('输出时次与队列不一致')
                    verify_assets(package,data['assets'])
                    update('verifying',utc=utc)
                    evidence=workers.verify(package) or package/'blender_reopen.json'
                    # Reopen proof must pass in this process too; a worker exit alone is insufficient.
                    try:journal.step(job,utc)
                    except ValueError:journal.submit(job,utc,package/'commit.json')
                    journal.verify(job,utc,evidence)
                    if state.get('first_sample') is None:state['first_sample']=utc
                    if not accepted(root,state):
                        update('awaiting-quality',utc=utc,package=str(package));return state
                    journal.approve_profile(job,user_quality_accepted=True)
                    update('cleaning',utc=utc)
                    retention=Retention(journal);cleanup=retention.plan(job,utc)
                    write_json(package/'cleanup_plan.json',cleanup)
                    result=retention.execute(cleanup);write_json(package/'cleanup_result.json',result)
                    state['completed'].append(utc)
                    update('step-complete',utc=utc,cleaned_files=result['deleted_files'])
                finally:journal.close()
            write_json(root/'sequence_index.json',dict(schema='earthstudio.layered_sequence.v1',nodes=plan['nodes'],
                frames=[dict(utc=s['utc'],commit=str(package_for(root,s['utc'],plan)/'commit.json')) for s in plan['steps']],
                limitations=['Source index references earlier accepted revisions; prepare a self-contained delivery before moving it.']))
            update('complete')
        except DownloadCancelled:
            update('paused-user');return state
        except Exception as error:
            import traceback
            from datetime import datetime,timezone
            failed_stage=state.get('phase')
            write_json(root/'last_failure.json',dict(occurred_utc=datetime.now(timezone.utc).isoformat(),scan_utc=state.get('utc'),stage=failed_stage,
                error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
            update('failed-inputs-preserved',error=str(error),error_stage=failed_stage);raise
        return state
