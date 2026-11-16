"""Live user targets, measured RAM peaks and incremental automatic admission."""
import json,shutil,subprocess,time
from pathlib import Path
import psutil
from .admission import GIB,MAX_SCANS,options
from .stage_resources import package_phase,can_start_science
from ges_next.production.assets import write_json


def gpu_free_bytes():
    executable=shutil.which('nvidia-smi')
    if not executable:return None
    try:
        result=subprocess.run([executable,'--query-gpu=memory.free','--format=csv,noheader,nounits'],
            capture_output=True,text=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return int(result.stdout.splitlines()[0])*1024**2 if result.returncode==0 else None
    except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):return None


class Concurrency:
    def __init__(self,root,limit,prefetch,profile=None):
        self.optional_ai=(profile or {}).get('NightMode') in ('ai-vis','ai-vis-ir')
        from .measured_defaults import load
        self.defaults=load(profile)
        self.root=Path(root);self.limit=limit;self.requested=limit;self.prefetch=prefetch;self.recommended=MAX_SCANS
        self.target=min(self.defaults.get('recommended_max_compute',2),limit);self.checked=0;self.reason='warming';self.gpu_free=None
        self.budget=6*GIB;self.cpu=0;self.available=0;self.control='auto';self.execution_mode='serial'
        self.thread_profiles={};self.compute_threads=0;self.decode_threads=0;self.actual_science=0
        self.history=[];self.science_by_threads={};self.live_peaks={};self.verification_history=[];self.finished=[];self.verification_budget=6*GIB
        file=self.root/'performance_samples.json'
        if file.exists():
            saved=json.loads(file.read_text(encoding='utf-8'));self.history=saved.get('peaks',[])[-20:]
            self.verification_history=saved.get('verification_peaks',[])[-20:]
            self.science_by_threads=saved.get('science_by_threads',{})
        for key,peaks in self.defaults.get('science_by_threads',{}).items():
            self.science_by_threads[key]=(peaks+self.science_by_threads.get(key,[]))[-20:]
        self.verification_history=(self.defaults.get('verification_peaks',[])+self.verification_history)[-20:]
        psutil.cpu_percent()

    def sample_completed(self,package):
        file=Path(package)/'performance.json'
        if file.exists():
            value=json.loads(file.read_text(encoding='utf-8'));peak=value.get('process_peak_rss_bytes',0)
            science=Path(package)/'science_worker.timing.json'
            if science.exists():peak=max(peak,json.loads(science.read_text(encoding='utf-8')).get('peak_tree_rss_bytes',0))
            if peak:
                self.history=(self.history+[peak])[-20:]
                count=value.get('science_spill',{}).get('requested_workers',0)
                if count:
                    key=str(count);self.science_by_threads[key]=(self.science_by_threads.get(key,[])+[peak])[-20:]
            verification=Path(package)/'verification_worker.timing.json'
            if verification.exists():
                peak=json.loads(verification.read_text(encoding='utf-8')).get('peak_tree_rss_bytes',0)
                if peak:self.verification_history=(self.verification_history+[peak])[-20:]
            write_json(self.root/'performance_samples.json',dict(peaks=self.history,verification_peaks=self.verification_history,
                science_by_threads=self.science_by_threads))
        self.finished.append(time.monotonic())

    def refresh(self,packages,ready,now=None):
        now=time.monotonic() if now is None else now
        if self.checked and now-self.checked<10:return False
        previous=self.details();self.checked=now
        self.actual_science=sum(package_phase(task)[1]=='producing' for task in packages)
        value=options(self.root);self.control=value.get('control','auto');self.execution_mode=value.get('mode','parallel')
        self.requested=value.get('max_compute',self.requested);self.prefetch=value.get('prefetch',self.prefetch)
        self.recommended=value.get('recommended_max_compute',self.defaults.get('recommended_max_compute',MAX_SCANS))
        self.limit=min(self.requested,self.recommended) if self.control=='auto' else self.requested
        if self.optional_ai:self.limit=min(3 if self.defaults.get("ai_gpu_slot_verified") else 1,self.limit)
        self.thread_profiles=value.get('thread_profiles',self.defaults.get('thread_profiles',{}));self.compute_threads=value.get('compute_threads',0)
        self.decode_threads=value.get('decode_threads',self.defaults.get('decode_threads',0))
        if self.execution_mode=='serial':self.limit=1
        else:self.limit=max(self.limit,self.minimum_science())
        self.live_peaks={}
        for task in packages:
            package,phase=package_phase(task)
            file=Path(package)/'scratch/work/reports/resource_usage.json'
            try:
                value=json.loads(file.read_text(encoding='utf-8'));key=str(value.get('science_spill',{}).get('requested_workers',0))
                self.live_peaks[key]=max(self.live_peaks.get(key,0),value.get('process_peak_rss_bytes',0))
            except (OSError,ValueError):pass
        self.budget=self.estimated_budget(self.thread_count())
        self.verification_budget=max(2*GIB,int(max(self.verification_history)*1.25)) if self.verification_history else 6*GIB
        self.cpu=psutil.cpu_percent();self.available=psutil.virtual_memory().available
        self.gpu_free=gpu_free_bytes()
        if self.control=='manual':
            self.target=self.limit
            # Only explain an admission block when another scan is actually
            # requested. At the target, a hypothetical extra scan is irrelevant.
            needs_more=ready and self.actual_science<self.target
            self.reason='minimum-three-priority' if needs_more and self.actual_science<self.minimum_science() else ('memory-or-vram-limit' if needs_more and not self.admit(packages) else 'manual-target')
        elif self.available<5*GIB:
            self.target=max(self.minimum_science() or 1,self.target-1);self.reason='minimum-three-priority' if self.minimum_science() else 'resource-pressure'
        elif ready and self.admit(packages):
            self.reason='measured-limit' if self.target>=self.limit and self.recommended<self.requested else 'headroom-ramp'
            self.target=min(self.limit,self.target+1)
        elif ready and not self.admit(packages):
            self.reason='memory-or-vram-limit'
        else:self.reason='waiting-for-input'
        self.target=min(max(self.target,self.minimum_science()),self.limit,MAX_SCANS)
        self.budget=self.estimated_budget(self.thread_count())
        return previous!=self.details()

    def minimum_science(self):
        if self.optional_ai:return 0
        # Explicit user override: a parallel request >=3 is a floor for
        # scientific scheduling, not merely an upper bound.
        return 3 if self.execution_mode=='parallel' and self.requested>=3 else 0

    def admit(self,packages):
        # CUDA allocations are small in this qualified recipe, but do not launch at VRAM exhaustion.
        self.budget=self.estimated_budget(self.thread_count())
        actual=sum(package_phase(task)[1]=='producing' for task in packages)
        if self.optional_ai:
            available=psutil.virtual_memory().available
            if actual>=self.limit or (self.gpu_free is not None and self.gpu_free<1536*1024**2):
                self.reason='ai-resource-admission';return False
            pair=self.defaults.get('qualified_pair_budget_bytes',0)
            if actual==1 and len(packages)==1 and pair>0 and self.defaults.get('ai_gpu_slot_verified'):
                # Qualified shared-GPU pipeline: measured combined peak already includes
                # both scans. Keep the15% envelope and4GiB OS reserve; never extrapolate to3.
                from .stage_resources import live_rss
                package,_=package_phase(packages[0])
                admitted=available>=4*GIB and available+live_rss(package,'science')>=4*GIB+pair
                if not admitted:self.reason='ai-resource-admission'
                return admitted
            if available<10*GIB:
                self.reason='ai-resource-admission';return False
        if actual<self.minimum_science():
            # Do not disguise this as passing the memory forecast.
            # User-selected floor overrides RAM/VRAM estimates only.
            return True
        tasks=[]
        for task in packages:
            package,phase=package_phase(task);threads=task.get('threads',0) if isinstance(task,dict) else 0
            tasks.append(dict(package=package,phase=phase,budget_bytes=self.estimated_budget(threads)))
        return (self.gpu_free is None or self.gpu_free>=768*1024**2) and can_start_science(
            tasks,self.budget,self.verification_budget,reserve=4*GIB)

    def details(self):
        return dict(control=self.control,requested=self.requested,target=self.target,reason=self.reason,recommended_max_compute=self.recommended,
            minimum_science=self.minimum_science(),admission_policy='minimum-three' if self.minimum_science() else 'resource-budget',
            actual_science=self.actual_science,ai_gpu_slots=1 if self.optional_ai else None,
            ai_resource_admission=self.optional_ai,
            cpu_percent=self.cpu,available_bytes=self.available,per_scan_budget_bytes=self.budget,
            gpu_free_bytes=self.gpu_free,system_reserve_bytes=4*GIB,verification_budget_bytes=self.verification_budget)

    def thread_count(self):
        if str(self.target) in self.thread_profiles:return self.thread_profiles[str(self.target)]
        if self.compute_threads:return self.compute_threads
        # A transient drop to one scan must not discard the known thread/RAM
        # calibration and get stuck behind an inflated unknown-worker budget.
        if self.thread_profiles:
            key=min(self.thread_profiles,key=lambda k:(abs(int(k)-self.target),int(k)))
            return self.thread_profiles[key]
        return 0

    def estimated_budget(self,threads):
        samples=self.science_by_threads.get(str(threads),[])
        if samples:
            margin=self.defaults.get('science_margin',1.25)
            return max(3*GIB,int(max(max(samples),self.live_peaks.get(str(threads),0))*margin))
        return max(6*GIB,int(max([*self.history,*self.live_peaks.values()],default=0)*1.25))

    def worker_environment(self):
        threads=self.thread_count()
        value={}
        if threads:value['EARTHSTUDIO_COMPUTE_THREADS']=str(threads)
        if self.decode_threads:value['EARTHSTUDIO_DECODE_THREADS']=str(self.decode_threads)
        return value
