"""Bounded synthetic operator/decode/video benchmark. Not a full H9 production timing."""
import bz2,json,os,subprocess,time,tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from ges_next.production.assets import write_json
from .policy import profile_path

def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    result=dict(scope='Synthetic independent BZ2 blocks, stock cloud-mask operators and display-only video; not a whole scan',host_logical_cpus=os.cpu_count())
    rng=np.random.default_rng(806);data=rng.integers(0,256,4*1024**2,dtype=np.uint8).tobytes();packed=bz2.compress(data)
    timings={}
    for workers in (2,4,8):
        start=time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            decoded=list(pool.map(bz2.decompress,[packed]*8))
        if any(value!=data for value in decoded):raise ValueError('Decode parity failed')
        timings[str(workers)]=time.perf_counter()-start
    result['decode_seconds']=timings;result['decode_workers']=int(min(timings,key=timings.get))
    result['decode_speedup_vs_2']=timings['2']/min(timings.values())
    del data,decoded,packed
    try:
        from ges.earth_validation.cuda_clouds import low_block
        a=rng.uniform(-2,6,(2048,2048)).astype(np.float32)
        b=np.full_like(a,250);mask=np.where(a>1,100,0).astype(np.float32)
        params=((100.,),(0.,),True,1.,0.,4.,0.,4.)
        def cpu():
            alpha=np.where(a<=0,np.float32(1),np.where(a>4,np.float32(0),np.float32(-.25)*a+np.float32(1)))
            return np.stack((a,np.float32(1)-alpha))
        expected=cpu();actual=low_block(a,b,mask,params)
        np.testing.assert_array_equal(actual,expected)
        values={}
        for name,fn in [('cpu',cpu),('cuda',lambda:low_block(a,b,mask,params))]:
            start=time.perf_counter()
            for _ in range(5):fn()
            values[name]=(time.perf_counter()-start)/5
        result['cloud_operator_seconds']=values;result['cuda_operator_exact']=True
        # Threshold/NaN/gamma qualification is separately run before enabling.
        result['cuda_candidate_faster']=values['cuda']<values['cpu']*.9
        from .qualification import qualify
        result['cuda_clouds_qualified']=qualify() and result['cuda_candidate_faster']
    except Exception as error:result['cuda_error']=str(error)
    import imageio_ffmpeg
    video={}
    for encoder,args in [('libx264',['-preset','fast','-crf','18']),('h264_nvenc',['-preset','p4','-cq','18'])]:
        start=time.perf_counter()
        process=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-f','lavfi','-i',
            'testsrc2=size=1920x960:rate=30:duration=4','-an','-c:v',encoder,*args,'-pix_fmt','yuv420p','-f','null','-'],capture_output=True)
        video[encoder]=dict(seconds=time.perf_counter()-start,passed=process.returncode==0)
    result['video_encoding']=video;result['nvenc_available']=video['h264_nvenc']['passed']
    if all(v['passed'] for v in video.values()):result['video_speedup']=video['libx264']['seconds']/video['h264_nvenc']['seconds']
    write_json(output/'hardware_benchmark.json',result);write_json(profile_path(),result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result

if __name__=='__main__':
    import sys
    run(sys.argv[1])
