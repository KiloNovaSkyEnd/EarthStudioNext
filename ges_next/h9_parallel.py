"""Independent native row processes; no scientific graph serialization or changes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys

GIB=1024**3

def admitted_rows(requested,physical_available,commit_available):
    if isinstance(requested,bool) or not isinstance(requested,int) or requested not in (1,2):
        raise ValueError('Only1 or2 independent row processes are qualified')
    return max(1,min(requested,(physical_available-6*GIB)//(3*GIB),
                     (commit_available-2*GIB)//(3*GIB)))

def row_command(args,script,row):
    command=[sys.executable,'-X','utf8','-u',str(script),'--utc',args.utc,
        '--raw',str(args.raw),'--reference',str(args.reference),'--night',str(args.night),
        '--output',str(args.output),'--scope-generation',str(args.scope_generation),'--row',str(row)]
    if args.shared_static_cache:command.extend(['--shared-static-cache',str(args.shared_static_cache)])
    if getattr(args,'performance_profile',None):command.extend(['--performance-profile',str(args.performance_profile)])
    return command

def run_rows(args,script,workers):
    if args.row is not None or args.assemble_only:
        raise ValueError('Only a coordinator may schedule row children')
    out=Path(args.output)
    def run(row):
        with (out/f'row_{row:05}.log').open('a',encoding='utf-8') as stream:
            subprocess.run(row_command(args,script,row),stdout=stream,stderr=subprocess.STDOUT,check=True)
        return row
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run,[0,5500,11000,16500]))


def dispatch_rows(args,script,workers):
    """Reuse the qualified in-process full scan when memory admits only one.

    Four sequential child startups cannot add parallelism. The caller already
    supports the identical single-scene/sixteen-tile route used for one row
    worker, including normal receipt verification and lossless assembly.
    """
    if isinstance(workers,bool) or not isinstance(workers,int) or workers not in (1,2):
        raise ValueError('Only1 or2 admitted row processes are qualified')
    if workers==1:return False
    run_rows(args,script,workers)
    return True
