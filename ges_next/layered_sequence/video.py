"""Stream display frames to a hardware encoder, with a complete software retry."""
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

def encode(root,frames,width,fps,preferred):
    import imageio_ffmpeg
    root=Path(root);target=root/'timelapse.mp4'
    encoders=[preferred]+(['libx264'] if preferred!='libx264' else [])
    last=None
    for encoder in encoders:
        options=['-c:v','h264_nvenc','-preset','p4','-cq','18'] if encoder=='h264_nvenc' else ['-c:v','libx264','-preset','fast','-crf','18']
        command=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{width//2}',
            '-r',str(fps),'-i','pipe:0','-an',*options,'-pix_fmt','yuv420p','-movflags','+faststart',str(target)]
        with (root/f'preview_encoding_{encoder}.log').open('w') as log:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log,stdout=subprocess.DEVNULL)
            try:
                previous=None
                for frame in frames:
                    if not frame['missing']:previous=root/frame['path']
                    with Image.open(previous or root/frame['path']) as image:
                        rgba=np.asarray(image).astype(np.uint16);alpha=rgba[:,:,3:4]
                        rgb=((rgba[:,:,:3]*alpha+np.array([68,73,78],np.uint16)*(255-alpha)+127)//255).astype(np.uint8)
                    process.stdin.write(rgb.tobytes())
                process.stdin.close()
                if process.wait()!=0:raise RuntimeError('Display video encoder failed')
                return encoder
            except (BrokenPipeError,RuntimeError) as error:last=error
            finally:
                if process.poll() is None:process.kill();process.wait()
    raise RuntimeError('预览编码失败；已保留正式素材，可查看编码日志') from last
