"""Lossless frame inspection and independently decoded H.264 verification."""
from pathlib import Path
import numpy as np
from PIL import Image
import imageio_ffmpeg
from .project import save


def encode(folder,count,width,height,name='camera_weather.mp4'):
    folder=Path(folder); target=folder/name; temporary=target.with_suffix('.part.mp4')
    checks=[]
    writer=imageio_ffmpeg.write_frames(str(temporary),(width,height),fps=24,codec='libx264',
        pix_fmt_in='rgb24',pix_fmt_out='yuv420p',macro_block_size=2,
        output_params=['-crf','18','-movflags','+faststart'])
    writer.send(None)
    try:
        for index in range(1,count+1):
            with Image.open(folder/'frames'/f'frame_{index:04d}.png') as image:
                image.verify()
            with Image.open(folder/'frames'/f'frame_{index:04d}.png') as image:
                pixels=np.asarray(image.convert('RGB'))
            if pixels.shape!=(height,width,3) or pixels.max()<3 or np.all(pixels==255):
                raise ValueError(f'Invalid or black rendered frame {index}')
            writer.send(np.ascontiguousarray(pixels)); checks.append({'frame':index,'mean':float(pixels.mean())})
    finally: writer.close()
    reader=imageio_ffmpeg.read_frames(str(temporary),pix_fmt='rgb24'); metadata=next(reader)
    decoded=0; previous=None; changed=False
    for value in reader:
        pixels=np.frombuffer(value,np.uint8)
        if pixels.max()<3: raise ValueError('Black frame in decoded video')
        if previous is not None and np.mean(np.abs(pixels.astype(np.float32)-previous))>.1: changed=True
        previous=pixels.astype(np.float32); decoded+=1
    if decoded!=count or not changed: raise ValueError('Decoded count or motion invalid')
    temporary.replace(target)
    result={'video':str(target),'decoded_frames':decoded,'fps':metadata['fps'],
        'shape':[height,width],'no_black_frames':True,'motion_or_weather_changes':changed,
        'frame_checks':checks,'visual_acceptance_passed':False}
    save(folder/'video_verification.json',result)
    return target
