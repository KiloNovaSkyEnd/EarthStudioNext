"""Throttled task counts for long scientific writes (not a timing forecast)."""
import time
from datetime import datetime,timezone
from dask.callbacks import Callback
from .project import save_report


class ComputeProgress(Callback):
    def __init__(self,path,scene_id):
        self.path=path; self.scene_id=scene_id; self.done=0; self.total=0; self.last=0
        super().__init__()
    def _start(self,dsk):
        self.total=len(dsk); self.began=time.monotonic(); self.write('running')
    def _posttask(self,key,result,dsk,state,worker_id):
        self.done+=1
        if time.monotonic()-self.last>3: self.write('running')
    def _finish(self,dsk,state,errored):
        self.write('failed' if errored else 'completed')
    def write(self,state):
        self.last=time.monotonic()
        save_report(self.path,{'scene_id':self.scene_id,'state':state,'finished_tasks':self.done,
            'graph_tasks':self.total,'seconds':self.last-self.began,
            'updated_utc':datetime.now(timezone.utc).isoformat(),
            'limits':'Task counts have unequal costs; not an ETA or pixel completeness proof'})
