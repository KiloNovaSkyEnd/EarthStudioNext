"""One independently verified scan, used by bounded parallel orchestration."""
import json,time
from .runner import journal_for,accepted
from ges_next.production.assets import verify_assets,write_json
from ges_next.production.retention import Retention
from ges_next.production.validation_session import ValidationSession
from ges_next.production.owned_files import CleanupSession


def process(step,package,job,profile,workers,verify_lock,root,state,progress):
    utc=step['utc'];journal=journal_for(package)
    began=time.perf_counter();events=[];notify=progress
    def progress(phase):
        events.append(dict(phase=phase,seconds=time.perf_counter()-began));notify(phase)
    try:
        if not (package/'commit.json').exists():
            progress('producing');workers.produce(step,package,profile)
        data=json.loads((package/'commit.json').read_text(encoding='utf-8'))
        if data['utc']!=utc:raise ValueError('输出时次与队列不一致')
        verify_assets(package,data['assets'])
        progress('waiting-verification')
        with verify_lock, ValidationSession():
            stage=workers.verification_stage(package) if hasattr(workers,'verification_stage') else 'verifying'
            progress(stage);evidence=workers.verify(package) or package/'blender_reopen.json'
            try:journal.step(job,utc)
            except ValueError:journal.submit(job,utc,package/'commit.json')
            journal.verify(job,utc,evidence)
            if not accepted(root,state):raise ValueError('首样验收记录已变化，保留输入')
            journal.approve_profile(job,user_quality_accepted=True)
            resources=package/'scratch/work/reports/resource_usage.json'
            if resources.exists():write_json(package/'performance.json',json.loads(resources.read_text(encoding='utf-8')))
            progress('cleaning');retention=Retention(journal)
            if hasattr(workers,'cleanup'):
                result=workers.cleanup(package)
            else:
                with CleanupSession() as cleanup_checks:
                    cleanup=retention.plan(job,utc)
                    write_json(package/'cleanup_plan.json',cleanup)
                    result=retention.execute(cleanup);write_json(package/'cleanup_result.json',result)
                write_json(package/'cleanup_validation.json',cleanup_checks.summary())
        return dict(utc=utc,cleaned_files=result['deleted_files'])
    finally:
        try:write_json(package/'pipeline_timing.json',dict(seconds=time.perf_counter()-began,events=events))
        finally:journal.close()
