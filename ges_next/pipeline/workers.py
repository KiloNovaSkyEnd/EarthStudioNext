"""Separate scientific processes release decoder/GPU handles before retention work."""
import json
from pathlib import Path
import subprocess
import sys
import queue
import threading
import time


def module(name,args,root,log,report,environment=None,watchdog=None):
    with Path(log).open('w',encoding='utf-8') as errors:
        import os
        import psutil
        from .stage_resources import tree_rss
        from ges_next.production.assets import write_json
        env=os.environ.copy();env.update(environment or {})
        began=time.perf_counter();events=[];peak_rss=0
        from .worker_watchdog import Watchdog,WorkerStalledError,stop_owned_tree
        if watchdog is None and name in ('ges_next.production','ges_next.production.package'):
            watchdog=Watchdog(stall_seconds=900 if name=='ges_next.production' else 1800,total_seconds=3600 if name=='ges_next.production' else 7200)
        watchdog_reason=None
        process=subprocess.Popen([sys.executable,'-X','utf8','-u','-m',name,*map(str,args)],cwd=root,
            stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8',env=env)
        try:created=psutil.Process(process.pid).create_time()
        except psutil.NoSuchProcess:created=None
        write_json(Path(log).with_suffix('.process.json'),dict(pid=process.pid,created=created,module=name))
        lines=queue.Queue()
        def reader():
            for line in process.stdout:lines.put(line)
        thread=threading.Thread(target=reader,daemon=True);thread.start()
        stamp=None;resource_stamp=None;tracked={};root_ended=None
        try:
            while process.poll() is None or not lines.empty() or thread.is_alive():
                if watchdog is None:peak_rss=max(peak_rss,tree_rss(process.pid,created))
                try:
                    line=lines.get(timeout=.5)
                    try:
                        value=json.loads(line)
                        if isinstance(value,dict) and value.get('phase'):
                            events.append(dict(phase=value['phase'],seconds=time.perf_counter()-began,reported_seconds=value.get('elapsed_seconds')))
                            if watchdog:watchdog.observe(time.monotonic(),phase=value['phase'])
                        report(value)
                    except json.JSONDecodeError:pass
                except queue.Empty:pass
                progress=Path(log).parent/'scratch/work/compute_progress.json'
                if name=='ges_next.production' and progress.is_file() and progress.stat().st_mtime_ns!=stamp:
                    try:
                        value=json.loads(progress.read_text(encoding='utf-8'));stamp=progress.stat().st_mtime_ns
                        report(dict(phase='computing',finished_tasks=value['finished_tasks'],graph_tasks=value['graph_tasks'],seconds=value['seconds']))
                        if watchdog:watchdog.observe(time.monotonic(),tasks=value['finished_tasks'])
                    except (KeyError,ValueError,OSError):pass
                resources=Path(log).parent/'scratch/work/reports/resource_usage.json'
                if name=='ges_next.production' and resources.is_file() and resources.stat().st_mtime_ns!=resource_stamp:
                    try:
                        value=json.loads(resources.read_text(encoding='utf-8'));resource_stamp=resources.stat().st_mtime_ns
                        report(dict(phase='hardware-usage',resources=value))
                    except (ValueError,OSError):pass
                if watchdog:
                    cpu=0;io=0;rss=0
                    try:
                        owner=psutil.Process(process.pid)
                        if created is not None and abs(owner.create_time()-created)>.01:raise psutil.NoSuchProcess(process.pid)
                        for item in [owner,*owner.children(recursive=True)]:
                            try:rss+=item.memory_info().rss
                            except psutil.Error:pass
                            try:
                                if item.pid!=process.pid:tracked[item.pid]=item.create_time()
                                counters=item.cpu_times();access=item.io_counters();cpu+=counters.user+counters.system;io+=access.read_bytes+access.write_bytes
                            except psutil.Error:pass
                    except psutil.Error:pass
                    peak_rss=max(peak_rss,rss)
                    watchdog_reason=watchdog.observe(time.monotonic(),cpu=cpu,io=io)
                    if process.poll() is not None and thread.is_alive():
                        if root_ended is None:root_ended=time.monotonic()
                        elif time.monotonic()-root_ended>=5:watchdog_reason='Launcher exited while owned child or stdout remained active'
                    if watchdog_reason:
                        stop_owned_tree(process,created,tracked)
                        raise WorkerStalledError(watchdog_reason+'; inputs preserved: '+str(log))
            if process.wait()!=0:raise RuntimeError('子任务失败，输入保留；日志：'+str(log))
        finally:
            if process.poll() is None or watchdog_reason:
                stop_owned_tree(process,created,tracked);process.wait(timeout=30)
            thread.join(timeout=5)
            if not thread.is_alive():process.stdout.close()
            write_json(Path(log).with_suffix('.timing.json'),dict(module=name,seconds=time.perf_counter()-began,
                peak_tree_rss_bytes=peak_rss,events=events,exit_code=process.returncode,watchdog_reason=watchdog_reason))


class Workers:
    def __init__(self,reference,night,cache,blender,report):
        self.reference,self.night,self.cache,self.blender=str(reference),str(night),str(cache),str(blender)
        self.report=report
        self.engine=Path(__file__).resolve().parents[2]
        self.environment={}

    def fork(self,report,slots):
        result=Workers(self.reference,self.night,self.cache,self.blender,report)
        result.environment={'EARTHSTUDIO_PARALLEL_SLOTS':str(slots)}
        return result

    def produce(self,step,package,profile):
        args=['--source-root',self.cache,'--reference',self.reference,'--utc',step['utc'],'--output',str(package),
              '--quality',str(profile['JpegQuality']),'--night-metres',str(profile['NightLightMetres']),'--inputs',str(package/'input_selection.json'),
              '--night-reference',self.night]
        if profile.get('KeepL1'):args.append('--keep-l1')
        if profile.get('NightMode'):args.extend(['--night-mode',profile['NightMode']])
        if profile.get('KeepIntermediates'):args.append('--keep-intermediates')
        module('ges_next.production',args,self.engine,package/'science_worker.log',self.report,self.environment)

    def verify(self,package):
        from .worker_validation import verify
        return verify(self,package)

    def verification_stage(self,package):
        from .worker_validation import selection
        return 'verifying-assets' if selection(package,self.blender)[0]=='assets' else 'verifying'

    def verify_blender(self,package):
        module('ges_next.production.package',[package,'--build-blender','--blender',self.blender],self.engine,package/'verification_worker.log',self.report,self.environment)

    def cleanup(self,package):
        from .worker_watchdog import Watchdog
        package=Path(package)
        module('ges_next.production.cleanup',[package],self.engine,package/'cleanup_worker.log',self.report,self.environment,
            watchdog=Watchdog(stall_seconds=300,total_seconds=1800))
        return json.loads((package/'cleanup_result.json').read_text(encoding='utf8'))
