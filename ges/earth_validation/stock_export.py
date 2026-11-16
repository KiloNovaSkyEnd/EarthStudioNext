"""Blender subprocess, resumable PNGs and decoded video verification."""
from pathlib import Path
import json
import subprocess
import numpy as np
from PIL import Image
import imageio_ffmpeg
from .project import save,check_disk
from .blender_assets import prepare


def export(root,blender):
    root=Path(root).resolve()
    if not Path(blender).is_file(): raise FileNotFoundError('Select an installed Blender executable')
    report=json.loads((root/'reports/stock_pilot.json').read_text(encoding='utf-8'))
    prepare(root,report)
    output=root/'exports/stock_pilot_v1'; output.mkdir(parents=True,exist_ok=True)
    check_disk(root,2_000_000_000)
    script=Path(__file__).resolve().parents[2]/'scripts/blender_stock_validation.py'
    blend=output/'earth_stock_pilot.blend'
    if not blend.is_file():
        with (root/'reports/blender_stock.log').open('a',encoding='utf-8') as log:
            subprocess.run([str(blender),'-b','--python-exit-code','1','--python',str(script),'--','--root',str(root)],
                           check=True,stdout=log,stderr=subprocess.STDOUT)
    # Separate scene creation from rendering: restarting never overwrites the
    # user's editable .blend. Each missing frame can be independently recovered.
    frames=output/'frames'; frames.mkdir(exist_ok=True)
    missing=[i for i in range(1,97) if not (frames/f'frame_{i:04d}.png').is_file()]
    if missing:
        render_log=root/'reports/blender_stock_render.log'
        log_start=render_log.stat().st_size if render_log.exists() else 0
        with render_log.open('a',encoding='utf-8') as log:
            subprocess.run([str(blender),'-b',str(blend),'--python-exit-code','1','-o',str(frames/'frame_'),
                '-F','PNG','-f',','.join(map(str,missing))],check=True,stdout=log,stderr=subprocess.STDOUT)
        with render_log.open('rb') as stream:
            stream.seek(log_start); run_log=stream.read().decode('utf-8',errors='replace')
        if 'Failed to load' in run_log or 'Loading weather_0000.png' in run_log:
            raise ValueError('Blender source texture loading failed; rendered frames not accepted')
    video=output/'weather_camera_pilot.mp4'
    temporary=output/'weather_camera_pilot.part.mp4'
    checks=[]
    writer=imageio_ffmpeg.write_frames(str(temporary),(960,540),fps=24,codec='libx264',
        pix_fmt_in='rgb24',pix_fmt_out='yuv420p',macro_block_size=2,
        output_params=['-crf','18','-movflags','+faststart'])
    writer.send(None)
    try:
        for i in range(1,97):
            with Image.open(frames/f'frame_{i:04d}.png') as im:
                im.verify()
            with Image.open(frames/f'frame_{i:04d}.png') as im:
                array=np.asarray(im.convert('RGB'))
            if array.shape!=(540,960,3) or np.all(array==255):
                raise ValueError('Unexpected image grid or all-white render')
            if np.max(array)<3: raise ValueError(f'Black render frame {i}')
            checks.append({'frame':i,'mean':float(array.mean()),'nonzero_fraction':float(np.count_nonzero(array)/array.size)})
            writer.send(np.ascontiguousarray(array))
    finally: writer.close()
    reader=imageio_ffmpeg.read_frames(str(temporary),pix_fmt='rgb24')
    metadata=next(reader); decoded=0; differences=[]; previous=None
    for frame in reader:
        array=np.frombuffer(frame,np.uint8)
        if array.max()<3: raise ValueError('Decoded video contains black frame')
        if previous is not None: differences.append(float(np.mean(np.abs(array.astype(np.float32)-previous))))
        previous=array.astype(np.float32); decoded+=1
    if decoded!=96 or not any(d>.1 for d in differences): raise ValueError('Video count/motion verification failed')
    temporary.replace(video)
    save(output/'video_verification.json',{'video':str(video),'decoded_frames':decoded,
        'fps':metadata['fps'],'no_all_black_frames':True,'frame_checks':checks,
        'camera_or_weather_changed':True,'visual_acceptance_passed':False,
        'full_73_nodes':False,'global_native_detail_passed':False,
        'limits':'Decoding and non-black checks do not replace visual or geographic acceptance'})
    return video
