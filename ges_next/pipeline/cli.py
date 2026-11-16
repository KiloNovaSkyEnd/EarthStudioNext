"""Native desktop boundary. Plan is read-only networking; run explicitly transfers payloads."""
import argparse
import json
import os
from pathlib import Path
from .plan import create
from .locking import exclusive,QueueBusyError


def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['plan','run','accept','revise'])
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--inventory',type=Path)
    parser.add_argument('--previous-queue',type=Path)
    parser.add_argument('--reuse-source',type=Path)
    parser.add_argument('--allow-missing',action='store_true')
    args=parser.parse_args()
    try:
        from .trial_dispatch import dispatch
        dispatch(args)
        if args.action=='revise':
            if not args.project or not args.inventory:raise ValueError('需要项目和预检目录')
            import uuid
            from .queue_changes import stage,effective,summary
            candidate=create(json.loads(args.project.read_text(encoding='utf-8')),args.inventory,args.queue/'change_candidates'/uuid.uuid4().hex)
            receipt=stage(args.queue,candidate)
            base=json.loads((args.queue/'plan.json').read_text(encoding='utf-8'))
            emit(dict(phase='planned',queue=str(args.queue.resolve()),plan=summary(effective(args.queue,base)),change=receipt));return
        if args.action=='plan':
            if not args.project or not args.inventory:raise ValueError('需要项目和预检目录')
            project=json.loads(args.project.read_text(encoding='utf-8'))
            if args.previous_queue and args.reuse_source:raise ValueError('追加与跨项目复用不能同时使用')
            if args.previous_queue and json.loads((args.previous_queue/'state.json').read_text(encoding='utf-8'))['phase']!='complete':
                from .queue_changes import live_append
                result=live_append(project,args.inventory,args.queue,args.previous_queue)
            else:result=create(project,args.inventory,args.queue,previous=args.previous_queue,reuse_source=args.reuse_source)
            emit(dict(phase='planned',queue=str(args.queue.resolve()),plan=result));return
        from .runner import load,run,accept_quality
        try:
            with exclusive(args.queue/'queue.lock'):pass
        except QueueBusyError:
            emit(dict(phase='queue-already-running',queue=str(args.queue.resolve())))
            return
        _,plan,_=load(args.queue)
        if args.project:
            from .plan import signature
            if signature(json.loads(args.project.read_text(encoding='utf-8'))) not in (plan['project'],plan.get('_base_project',plan['project'])):raise ValueError('当前项目、时间、卫星、存储或制作设置不匹配。请打开此队列所属的项目；修改设置后需重新预检并建立新队列')
        from ges_next.night_resources import resolve
        night=resolve(check_pixels=True,metres=plan['project']['Production']['NightLightMetres'])  # Fail before any L1 transfer or quality acceptance.
        from ges_next.reference_resources import resolve as resolve_reference
        reference=resolve_reference()  # Resolve before acceptance, guardian startup or payload transfer.
        if args.action=='accept':accept_quality(args.queue)
        from .workers import Workers
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        root=Path(__file__).resolve().parents[2]
        cache=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
        workers=Workers(reference,
            night,cache,os.environ.get('EARTHSTUDIO_BLENDER','blender.exe'),emit)
        client=boto3.client('s3',region_name='us-east-1',config=Config(signature_version=UNSIGNED,connect_timeout=10,read_timeout=30,max_pool_connections=12,retries={'max_attempts':4,'mode':'standard'}))
        from .admission import options
        execution=options(args.queue)
        from .retry_book import enabled as unattended_enabled
        from ges_next.production.assets import write_json
        import psutil
        write_json(args.queue/'engine_owner.json',dict(pid=os.getpid(),created=psutil.Process().create_time(),module='ges_next.pipeline.cli'))
        policy=json.loads((args.queue/'unattended.json').read_text(encoding='utf-8')) if (args.queue/'unattended.json').exists() else dict(enabled=True)
        policy['last_allow_missing']=bool(args.allow_missing);write_json(args.queue/'unattended.json',policy)
        if unattended_enabled(args.queue):
            from .guardian import ensure
            try:ensure(args.queue)
            except Exception as error:emit(dict(phase='guardian-unavailable',error=str(error),message='Queue continues; independent guardian could not start'))
        from .power import keep_awake
        with keep_awake(emit):
            if execution.get('mode')=='parallel' or unattended_enabled(args.queue):
                from .parallel import run as parallel_run
                parallel_run(args.queue,client,workers,cache,args.allow_missing,emit,
                    max_compute=1 if execution.get('mode')=='serial' else execution.get('max_compute',8),prefetch=execution.get('prefetch',3))
            else:run(args.queue,client,workers,cache,args.allow_missing,emit)
    except QueueBusyError as error:
        if error.path==(args.queue/'queue.lock').resolve():
            emit(dict(phase='queue-already-running',queue=str(args.queue.resolve())))
            return
        emit(dict(phase='error',error=str(error)));raise SystemExit(1)
    except Exception as error:
        emit(dict(phase='error',error=str(error)));raise SystemExit(1)


if __name__=='__main__':main()
