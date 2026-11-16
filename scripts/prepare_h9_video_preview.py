"""Encode one bounded display-only movie; native assets remain read-only."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
import numpy as np
from PIL import Image
import imageio_ffmpeg
from ges_next.isolation import require_writable

root=Path(__file__).resolve().parents[1]
folder=require_writable(root/'data/cesium_h9_motion_20261020')
manifest_path=folder/'manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Need1GB free display-video budget')
frames=manifest['frames'];paths=[];previous=None;mapping=[]
digest=hashlib.sha256(b'H9-display-video-v1-nvenc-cq19-12fps')
for index,frame in enumerate(frames):
    if frame.get('missing'):
        if previous is None:raise ValueError('Leading missing frame unsupported')
        mapping.append(dict(index=index,requestedUtc=frame['utc'],observationState='missing',displayedObservationUtc=previous[1],displayPolicy='hold-last-labeled'))
        paths.append(previous[0])
    else:
        path=folder/frame['previewPath']
        # Encode losslessly prepared PNG, not the compressed still-display derivative.
        path=path.with_name(path.name.replace('_q88.webp','.png'))
        if not path.is_file():raise FileNotFoundError(path)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        previous=(path,frame['utc']);paths.append(path)
        mapping.append(dict(index=index,requestedUtc=frame['utc'],observationState='observed',displayedObservationUtc=frame['utc']))
digest.update(b'per-frame-alpha-composite-gray')
token=digest.hexdigest()[:16];out=folder/f'timelapse_{token}.mp4'
info_path=folder/f'timelapse_{token}.json';log=root/'reports/h9_web_bridge/video_encoding.log'
started=time.perf_counter()
if not out.is_file():
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    temporary=out.with_suffix('.partial.mp4')
    command=[ffmpeg,'-hide_banner','-y','-f','rawvideo','-pix_fmt','rgb24','-s','4096x2048','-r','12','-i','pipe:0','-an','-c:v','h264_nvenc','-preset','p5','-rc','vbr','-cq','19','-b:v','0','-g','12','-pix_fmt','yuv420p','-movflags','+faststart',str(temporary)]
    with log.open('w',encoding='utf-8') as receipt:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=receipt)
        try:
            for i,path in enumerate(paths):
                pixels=np.asarray(Image.open(path).convert('RGBA'))
                # No-data footprint can vary at the sensor limb. Composite each
                # actual alpha onto the existing no-observation grey, never fill
                # it with imagery from another satellite or time.
                alpha=pixels[:,:,3:4].astype(np.uint16)
                rgb=((pixels[:,:,:3].astype(np.uint16)*alpha+np.array([68,73,78],np.uint16)*(255-alpha)+127)//255).astype(np.uint8)
                process.stdin.write(rgb.tobytes())
                print(f'VIDEO_FRAME {i+1}/{len(paths)} {mapping[i]["requestedUtc"]}',flush=True)
            process.stdin.close()
            if process.wait()!=0:raise RuntimeError('NVENC video encode failed; inspect video_encoding.log')
        except BaseException:
            process.kill();process.wait();raise
    os.replace(temporary,out)
info=dict(schema='earthstudio.video-preview.v1',path=out.name,width=4096,height=2048,fps=12,frames=len(paths),lastFrameTime=(len(paths)-1)/12,bytes=out.stat().st_size,sha256=hashlib.sha256(out.read_bytes()).hexdigest(),encoder='h264_nvenc',displayOnly=True,nativeAssetsUnchanged=True,gapPolicy='hold-last-labeled',mapping=mapping,encodingSeconds=time.perf_counter()-started)
info_path.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
manifest['videoPreview']={k:info[k] for k in ['path','width','height','fps','frames','lastFrameTime','bytes','sha256','gapPolicy']}
temporary=manifest_path.with_suffix('.tmp');temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,manifest_path)
print(json.dumps(info|{'mapping':f'{len(mapping)} labeled nodes'},ensure_ascii=False),flush=True)
