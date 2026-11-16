import json,os
from pathlib import Path

def profile_path():return Path(__file__).resolve().parents[2]/'resources/performance/hardware_profile.json'

def settings():
    import psutil
    available=psutil.virtual_memory().available;cores=os.cpu_count() or 2
    workers=max(1,min(8,cores//2,int((available-4*1024**3)//(512*1024**2))))
    value=dict(compute_workers=workers,decode_workers=min(8,max(2,cores//2)),
        spill_bytes=min(4*1024**3,max(512*1024**2,int(available*.16))),cuda_clouds=False,video_encoder='libx264')
    path=profile_path()
    if path.exists():
        benchmark=json.loads(path.read_text(encoding='utf-8'))
        if benchmark.get('host_logical_cpus')==cores:
            value['decode_workers']=max(1,min(8,int(benchmark.get('decode_workers',2))))
            value['cuda_clouds']=benchmark.get('cuda_clouds_qualified') is True
            value['video_encoder']='h264_nvenc' if benchmark.get('nvenc_available') else 'libx264'
    slots=max(1,int(os.environ.get('EARTHSTUDIO_PARALLEL_SLOTS','1')))
    if slots>1:
        value['compute_workers']=min(value['compute_workers'],max(1,cores//slots))
        value['decode_workers']=min(value['decode_workers'],max(1,8//slots))
        value['spill_bytes']=min(value['spill_bytes'],2*1024**3)
    for key,variable in [('compute_workers','EARTHSTUDIO_COMPUTE_THREADS'),('decode_workers','EARTHSTUDIO_DECODE_THREADS')]:
        count=int(os.environ.get(variable,'0'))
        if not 0<=count<=8:raise ValueError('Explicit worker count must be0–8')
        if count:value[key]=count
    return value
