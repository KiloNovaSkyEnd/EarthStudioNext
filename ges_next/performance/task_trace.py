"""Opt-in local-Dask task groups; observation only, never alters task results."""
from collections import defaultdict
import time
from dask.callbacks import Callback


def group(key):
    name=str(key[0] if isinstance(key,tuple) else key)
    head,_,tail=name.rpartition('-')
    return head if len(tail)>=16 and all(c in '0123456789abcdef' for c in tail.lower()) else name


class TaskTrace(Callback):
    def __init__(self):
        self.starts={};self.groups=defaultdict(lambda:dict(calls=0,task_elapsed_seconds=0,maximum_seconds=0))
        self.graphs=[];self.live_graphs={};super().__init__()
    def _start(self,dsk):
        row=dict(tasks=len(dsk),began=time.perf_counter())
        self.graphs.append(row);self.live_graphs[id(dsk)]=row
    def _pretask(self,key,dsk,state):self.starts[key]=time.perf_counter()
    def _posttask(self,key,result,dsk,state,worker_id):
        elapsed=time.perf_counter()-self.starts.pop(key);row=self.groups[group(key)]
        row['calls']+=1;row['task_elapsed_seconds']+=elapsed;row['maximum_seconds']=max(row['maximum_seconds'],elapsed)
    def _finish(self,dsk,state,errored):
        row=self.live_graphs.pop(id(dsk))
        row.update(seconds=time.perf_counter()-row.pop('began'),errored=errored)
    def summary(self):
        return dict(graphs=self.graphs,groups=sorted([dict(group=k,**v) for k,v in self.groups.items()],key=lambda r:r['task_elapsed_seconds'],reverse=True),
            limits='Task elapsed includes scheduler/worker wait and overlaps across threads; not CPU time or GPU kernel duration. Opt-in trial instrumentation only.')
