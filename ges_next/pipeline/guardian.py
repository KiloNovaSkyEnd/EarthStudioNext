"""Independent, single-queue supervisor. Explicit user pauses always win.

The bootstrap exits before the long-lived guardian starts supervising, so closing
the desktop's process tree cannot also kill its own recovery service.
"""
import argparse,json,os,subprocess,sys,threading,time
from datetime import datetime,timezone
from pathlib import Path
import psutil
from .locking import exclusive,QueueBusyError
from ges_next.production.assets import write_json

ROOT=Path(__file__).resolve().parents[2]
TERMINAL=('complete','awaiting-quality','awaiting-missing-decision')
PAUSED=('paused-user','paused','paused-resources','paused-space')
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def alive(pid,created):
    try:return abs(psutil.Process(pid).create_time()-created)<.01
    except (psutil.Error,TypeError):return False
def decision(phase,*,busy=False,explicit_pause=False,cancelled=False,ui_alive=False,armed=True):
    if phase in TERMINAL:return 'idle'
    if explicit_pause or phase in PAUSED:return 'user-paused'
    if busy:return 'watching'
    if cancelled and ui_alive:return 'user-paused'
    if not armed:return 'user-paused'
    return 'recover'
def matches(args,queue):
    try:
        return ('ges_next.pipeline.cli' in args and ('run' in args or 'accept' in args) and Path(args[args.index('--queue')+1]).resolve()==queue)
    except (ValueError,IndexError):return False
def discover(queue,scan=True):
    receipt=queue/'engine_owner.json'
    if receipt.is_file():
        try:
            data=read(receipt);p=psutil.Process(data['pid'])
            if abs(p.create_time()-data['created'])<.01 and matches(p.cmdline(),queue):return p
        except (OSError,ValueError,KeyError,psutil.Error):pass
    if not scan:return None
    values=[]
    for p in psutil.process_iter(['pid','ppid','name']):
        if (p.info['name'] or '').lower() not in ('python.exe','pythonw.exe','python','python3','python3.12'):continue
        try:
            if matches(p.cmdline(),queue):values.append(p)
        except psutil.Error:pass
    ids={p.pid for p in values}
    roots=[p for p in values if p.info['ppid'] not in ids]
    return min(roots,key=lambda p:p.create_time()) if roots else None
def desktop_owner(engine):
    try:
        for parent in engine.parents():
            if parent.name().lower()=='earthstudio.app.exe':return dict(pid=parent.pid,created=parent.create_time())
    except psutil.Error:pass
    return None
def busy(queue):
    try:
        with exclusive(queue/'queue.lock'):return False
    except QueueBusyError:return True
def cancelled_exit(value):return value in (-1,4294967295)

def pause_context(state,pause_stamp,engine_created=None,engine_alive=False):
    """Do not mistake a previous engine's paused snapshot for a new user stop."""
    phase=state['phase'];updated=0
    try:updated=datetime.fromisoformat(state['updated_utc']).timestamp()
    except (KeyError,ValueError):pass
    if engine_created is not None:
        explicit=pause_stamp>=engine_created
        stale=phase in PAUSED and engine_alive and max(updated,pause_stamp)<engine_created
    else:explicit=False;stale=False
    return ('checking-completed' if stale else phase),explicit,max(pause_stamp,updated)

class ExitObservation:
    def __init__(self,process):
        self.pid=process.pid;self.created=process.create_time();self.code=None;self.finished=False
        def wait():
            try:self.code=process.wait()
            except psutil.Error:pass
            finally:self.finished=True
        threading.Thread(target=wait,daemon=True,name='owned-queue-exit').start()
    def is_alive(self):return alive(self.pid,self.created)

def bootstrap(queue):
    from ges_next.isolation import require_writable
    queue=require_writable(queue)
    folder=queue/'guardian';folder.mkdir(exist_ok=True)
    with (folder/'service.log').open('ab') as log:
        p=subprocess.Popen([sys.executable,'-X','utf8','-u','-m','ges_next.pipeline.guardian','--queue',str(queue)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return p.pid

def ensure(queue):
    """Short intermediate parent; native Kill(true) cannot reach an orphan guardian."""
    from ges_next.isolation import require_writable
    queue=require_writable(queue);folder=queue/'guardian';folder.mkdir(exist_ok=True)
    try:
        with exclusive(folder/'service.lock'):pass
    except QueueBusyError:return
    subprocess.run([sys.executable,'-X','utf8','-m','ges_next.pipeline.guardian','--queue',str(queue),'--bootstrap'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)

def serve(queue):
    from ges_next.isolation import require_writable
    queue=require_writable(queue);folder=queue/'guardian';folder.mkdir(exist_ok=True)
    from .worker_watchdog import stop_owned_tree
    from .retry_book import enabled
    control=folder/'control.json'
    saved=read(control) if control.exists() else {}
    previous_pause=0;armed=saved.get('armed',True);observed=None;ui=None;attempt=0;next_try=0;service_began=time.time()
    previous_progress=None;progress_at=time.monotonic();tracked={};forced_restart=False;last_discover=0;last_command=None
    power=None
    if os.name=='nt':
        import ctypes
        power=ctypes.windll.kernel32.SetThreadExecutionState
    awake=False
    try:
        with exclusive(folder/'service.lock'):
            while enabled(queue):
                stop_file=folder/'stop_requested.json'
                if stop_file.exists() and stop_file.stat().st_mtime>=service_began:break
                now=time.time();state=read(queue/'state.json');phase=state['phase']
                locked=busy(queue)
                # A new engine after a deliberate Continue re-arms supervision.
                if now-last_discover>=10 and (observed is None or not observed.is_alive()):
                    last_discover=now;p=discover(queue,scan=locked)
                    if p is not None and (observed is None or p.pid!=observed.pid or abs(p.create_time()-observed.created)>.01):
                        observed=ExitObservation(p)
                        if observed.created>saved.get('paused_unix',0):
                            armed=True;saved=dict(armed=True);write_json(control,saved)
                        forced_restart=False;tracked={};progress_at=time.monotonic();previous_progress=None
                        ui=desktop_owner(p) or ui
                        previous_pause=(queue/'pause_requested.json').stat().st_mtime if (queue/'pause_requested.json').exists() else 0
                        last_command=p.cmdline()
                pause_stamp=(queue/'pause_requested.json').stat().st_mtime if (queue/'pause_requested.json').exists() else 0
                live=observed is not None and observed.is_alive()
                effective,explicit,pause_time=pause_context(state,pause_stamp,observed.created if observed else None,live)
                if explicit or effective in PAUSED:
                    if armed:saved=dict(armed=False,paused_unix=pause_time or now);write_json(control,saved)
                    armed=False
                app_alive=ui is not None and alive(ui['pid'],ui['created'])
                cancelled=bool(observed and observed.finished and cancelled_exit(observed.code) and not forced_restart)
                # Allow the desktop to finish closing after it cancels its child.
                if cancelled and app_alive and not locked:
                    time.sleep(3);app_alive=alive(ui['pid'],ui['created'])
                action=decision(effective,busy=locked or live,explicit_pause=explicit,cancelled=cancelled,ui_alive=app_alive,armed=armed)
                if action=='user-paused':
                    if armed:saved=dict(armed=False,paused_unix=now);write_json(control,saved)
                    armed=False
                progress=[len(state.get('completed',[])),state.get('checked_completed',0)]
                working=phase in ('checking-completed','failed-inputs-preserved') and live
                for task in state.get('active',[]):
                    tphase=task['phase'];item=[task['utc'],tphase]
                    if tphase in ('producing','verifying','verifying-assets','cleaning'):working=True
                    path=queue/'steps'/task['utc'].replace('-','').replace(':','')/'scratch/work/compute_progress.json'
                    if path.is_file():
                        try:item.append(read(path).get('finished_tasks'))
                        except (OSError,ValueError):pass
                    progress.append(item)
                if progress!=previous_progress:progress_at=time.monotonic();previous_progress=progress
                if observed and observed.is_alive():
                    try:
                        for child in psutil.Process(observed.pid).children(recursive=True):tracked[child.pid]=child.create_time()
                    except psutil.Error:pass
                # A live JSON heartbeat is insufficient evidence of real work.
                if action=='watching' and working and time.monotonic()-progress_at>1800 and observed and observed.is_alive():
                    proxy=psutil.Process(observed.pid)
                    class Owned:
                        pid=proxy.pid
                        def kill(self):proxy.kill()
                    stop_owned_tree(Owned(),observed.created,tracked);forced_restart=True;action='recover';next_try=now+15
                if action=='recover' and now>=next_try:
                    # Re-check the queue lock immediately before launching. The
                    # worker owns final exclusion too; duplicate launchers do not
                    # modify another owner's state.
                    from .runner import accepted
                    if not accepted(queue,state):action='waiting-acceptance'
                    elif not busy(queue):
                        attempt+=1;delay=min(300,15*2**min(attempt-1,5));next_try=now+delay
                        args=[sys.executable,'-X','utf8','-u','-m','ges_next.pipeline.cli','run','--queue',str(queue)]
                        project=queue/'current_request.earthproj'
                        if project.is_file():args.extend(['--project',str(project)])
                        plan=read(queue/'plan.json')
                        # The existing queue already carries the human's missing-
                        # observation decision; never invent observations.
                        if plan.get('missing_nodes') and read(queue/'unattended.json').get('last_allow_missing') is True:args.append('--allow-missing')
                        with (folder/('worker_'+str(attempt)+'.log')).open('ab') as log:
                            p=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        observed=ExitObservation(psutil.Process(p.pid));forced_restart=False;tracked={};last_command=args;progress_at=time.monotonic();action='recovering-worker'
                should_awake=armed and action not in ('idle','user-paused')
                if power and should_awake!=awake:
                    accepted_power=power(0x80000001 if should_awake else 0x80000000)
                    if accepted_power:awake=should_awake
                write_json(folder/'status.json',dict(pid=os.getpid(),created=psutil.Process().create_time(),utc=datetime.now(timezone.utc).isoformat(),phase=action,armed=armed,attempt=attempt,queue_phase=phase,completed=len(state.get('completed',[])),engine=None if observed is None else dict(pid=observed.pid,created=observed.created,alive=observed.is_alive(),exit_code=observed.code),desktop=ui,power_guard_active=awake,next_retry_unix=next_try,last_work_progress_seconds=time.monotonic()-progress_at,command=last_command))
                if phase=='complete':break
                time.sleep(5)
    finally:
        if power and awake:power(0x80000000)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--queue',type=Path,required=True);parser.add_argument('--bootstrap',action='store_true');args=parser.parse_args()
    from ges_next.isolation import require_writable
    queue=require_writable(args.queue)
    if args.bootstrap:bootstrap(queue)
    else:
        while True:
            try:serve(queue);return
            except QueueBusyError:return
            except Exception as error:
                try:write_json(queue/'guardian/service_error.json',dict(utc=datetime.now(timezone.utc).isoformat(),error_type=type(error).__name__,error=str(error),retry_seconds=15))
                except OSError:pass
                time.sleep(15)
if __name__=='__main__':main()
