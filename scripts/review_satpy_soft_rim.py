"""Only night oblique + disk edge diagnostics; cached stock Satpy colours."""
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image
from pyproj import CRS
import imageio_ffmpeg
from ges.satpy_globe import SatpyGlobeRenderer,PROFILE
from ges.atmosphere_scattering import geographic
from scripts.render_champi_review import camera

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/exports/Satpy_GeoColor_Soft_Rim_v1'


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def load(kind):
    if kind=='night':
        folder=ROOT/'data/processed/satpy_night_review_20261020T1920Z'
        path=folder/'geo_color.png';meta=json.loads((folder/'metadata.json').read_text())
    else:
        folder=ROOT/'data/exports/champi_satpy_direct_20261020T2240Z'
        path=folder/'champi_geocolor_disk.png';meta=json.loads((folder/'disk_metadata.json').read_text())
        meta['projection']=CRS.from_user_input(meta['projection']).to_dict()
    assert sha(path)==meta['sha256']
    Image.MAX_IMAGE_PIXELS=None
    with Image.open(path) as source:rgb=np.array(source.convert('RGB'))
    return rgb,meta,path


def main(disk_only=False):
    OUT.mkdir(exist_ok=True)
    records=[]
    for kind in (['disk'] if disk_only else ['night','disk']):
        rgb,meta,path=load(kind)
        r=SatpyGlobeRenderer(rgb,meta,1280,800,2)
        del rgb
        cam=camera(117,15,800,131.4,17.4,32) if kind=='night' else dict(position=geographic(140.7,0,42164),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=21.)
        try:
            for enabled in [True,False]:
                name=kind+('_soft.png' if enabled else '_no_atmosphere.png')
                if not (OUT/name).exists():
                    Image.fromarray(r.render(cam,atmosphere=enabled,airglow=enabled)).save(OUT/name)
                records.append(dict(file=name,utc=meta['nominal_utc'],source=str(path),source_sha256=meta['sha256'],gpu=r.device,profile=PROFILE,atmosphere=enabled))
                print('SAVED',name,flush=True)
        finally:r.close()
    if disk_only:return
    rgb,meta,path=load('night')
    r=SatpyGlobeRenderer(rgb,meta,640,400,1)
    del rgb
    frames=[]
    for t in np.linspace(0,1,13):
        frames.append(camera(115+4*t,15+np.sin(t*np.pi),800+250*np.sin(t*np.pi),131.4,17.4,32))
    sequence=frames+frames[-2::-1]
    writer=imageio_ffmpeg.write_frames(str(OUT/'night_camera.mp4'),(1280,400),fps=12,codec='libx264',pix_fmt_in='rgb24',pix_fmt_out='yuv420p',macro_block_size=2,output_params=['-crf','18','-movflags','+faststart'])
    writer.send(None)
    originals={};error=0
    try:
        for i,cam in enumerate(sequence):
            on=r.render(cam);off=r.render(cam,False,False)
            pair=np.concatenate([on,off],axis=1)
            if i<13:originals[i]=pair
            else:error=max(error,int(np.abs(pair.astype(int)-originals[24-i].astype(int)).max()))
            writer.send(pair)
    finally:writer.close();r.close()
    assert error==0
    report=dict(profile=PROFILE,stills=records,motion_frames=25,motion_fps=12,return_max_dn=error,
        image_processing='Stock Satpy 0.60.0 geo_color and enhancements; no project blend, cloud alpha, height, night tint or extra lights',
        atmosphere='Art-directed desaturated Gaussian rim, width18km outside/2km inside; no ozone extinction or added white contour',
        limits='Himawari visible hemisphere, not global fusion. Native preview, Blender unverified. Fixed scan camera test, not weather interpolation.')
    (OUT/'review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    html='''<!doctype html><meta charset="utf-8"><title>Satpy GeoColor · 柔和大气验收</title>
<style>body{max-width:1300px;margin:28px auto;background:#090e16;color:#dce6f2;font:18px sans-serif}img,video{width:100%}a{color:#9cf}</style>
<h1>Satpy GeoColor · 柔和低饱和度大气</h1>
<p>颜色与昼夜合成直接使用Satpy 0.60.0官方geo_color及增强。自研云图处理暂时封存。无云高、额外云色、额外夜光或二次太阳交接。</p>
<h2>夜间侧视 · 2026-10-20 19:20 UTC</h2><a href="night_soft.png"><img src="night_soft.png"></a>
<details><summary>同一Satpy影像：完全关闭额外大气</summary><img src="night_no_atmosphere.png"></details>
<h2>夜间连续运镜：左侧柔和气辉，右侧关闭大气</h2><p>真实19:20固定扫描；改变机位与高度后原路返回，不是天气补帧。</p><video controls loop src="night_camera.mp4"></video>
<h2>圆盘边缘检查 · 2026-10-20 22:40 UTC</h2><p>复用已保存的11000px官方Satpy GeoColor，不另算日间云图；包含实际晨昏。未叠加白色轮廓。下方无大气对照可区分原始云层与额外光晕。</p><img src="disk_soft.png">
<details><summary>圆盘：关闭额外大气</summary><img src="disk_no_atmosphere.png"></details>
<p>以上为向日葵可见半球，非全球拼图。Satpy夜光为静态2016参考。大气为美术化显示；Native预览已测试，Blender端尚未验证。</p>'''
    (OUT/'index.html').write_text(html,encoding='utf-8')
    print('DONE',OUT,flush=True)


if __name__=='__main__':main()
