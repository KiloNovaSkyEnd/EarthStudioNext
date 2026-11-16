"""Decode every review frame, encode a viewing copy and build a local report."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--diagnostics', type=Path, required=True)
    args = parser.parse_args()
    root, diagnostics = args.root.resolve(), args.diagnostics.resolve()
    if (root/'acceptance_rejection.json').exists():
        raise RuntimeError('Rejected trial: do not package numerical checks as visual acceptance.')
    render = json.loads((root/'render_report.json').read_text(encoding='utf-8'))
    verification = json.loads((diagnostics/'verification.json').read_text(encoding='utf-8'))
    assert verification['passed']
    count = len(render['renders'])
    assert [r['frame'] for r in render['renders']] == list(range(1,count+1))
    frames = []
    for i in range(1,count+1):
        path = root/'frames'/f'frame_{i:04d}.png'
        with Image.open(path) as image:
            image.load()
            assert image.size == (1280,720)
            values = np.asarray(image.convert('RGB'))
            frames.append(dict(frame=i,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               mean_dn=float(values.mean()),nonblack_fraction=float((values.max(-1)>0).mean())))
    assert len({f['sha256'] for f in frames}) > count*.95
    video = root/'01_大气与气辉_连续运镜.mp4'
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg,'-hide_banner','-nostdin','-n','-framerate','24','-i',str(root/'frames/frame_%04d.png'),
                    '-frames:v',str(count),'-c:v','libx264','-crf','16','-preset','medium','-pix_fmt','yuv420p',
                    '-movflags','+faststart',str(video)],check=True)
    probe = subprocess.run([ffmpeg,'-hide_banner','-nostdin','-i',str(video),'-f','null','-'],capture_output=True,text=True)
    assert probe.returncode == 0,probe.stderr
    (root/'video_decode.log').write_text(probe.stderr,encoding='utf-8')
    compare = root/'comparisons'
    compare.mkdir(exist_ok=False)
    for path in diagnostics.glob('*.png'):
        shutil.copy2(path,compare/path.name)
    shutil.copy2(diagnostics/'verification.json',root/'verification.json')
    samples = np.rint(np.linspace(1,count,8)).astype(int)
    sheet = Image.new('RGB',(1280,800),(7,12,20))
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
    draw = ImageDraw.Draw(sheet)
    for index,frame in enumerate(samples):
        x,y = index%2*640,index//2*200
        with Image.open(root/'frames'/f'frame_{frame:04d}.png') as image:
            image.thumbnail((640,180))
            sheet.paste(image,(x,y+20))
        draw.text((x+10,y),f'镜头 {frame}/{count} · {frame/24:.2f} 秒',font=font,fill='#cbd9ec')
    sheet.save(root/'02_连续镜头总览.jpg',quality=94)
    report = dict(rendered_frames=count,fps=24,duration_seconds=count/24,
                  fully_decoded_pngs=count,video_fully_decoded=True,frames=frames,
                  render_seconds=sum(r['seconds'] for r in render['renders']),
                  render_device=render['devices'],source_sha256=render['source_sha256'],
                  limitations=['Weather and UTC frozen; this is camera motion, not weather timelapse.',
                               'New Cycles volume candidate, not the accepted GLSL atmosphere port.',
                               'Actual daytime RGB is GOES16/17 only; other areas explicitly IR display.',
                               'Existing processed 8K composite, not full-native global detail or 3D cloud volume.',
                               'Acceptance of appearance belongs to the user; tests do not certify photorealism.'])
    (root/'delivery_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    phases = [(1,'远景 / 白天'),(round(count*.52),'近景 / 晨昏'),(count,'夜侧 / 气辉')]
    html = '''<!doctype html><meta charset="utf-8"><title>Blender 大气运镜验收</title>
<style>body{background:#080e18;color:#dce7f8;font:17px/1.8 system-ui;margin:32px auto;max-width:1280px;padding:0 24px}a{color:#8ecaff}video,img{max-width:100%;background:black}section{padding:20px 0;border-bottom:1px solid #243044}.row{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}small{color:#9eafc8}button{background:#20354e;color:white;border:1px solid #42617e;padding:12px}</style>
<h1>Blender 大气与气辉：真实相机运镜验收</h1>
<p>本页交付实际 Blender 渲染。先看连续视频，再查看下方同机位开关对照。原生三维体积参与相机射线，没有使用固定视角的大气成片贴图。</p>
<video id="movie" controls loop preload="metadata" src="01_大气与气辉_连续运镜.mp4" poster="02_连续镜头总览.jpg"></video>
<p><button onclick="document.getElementById('movie').playbackRate=.5">半速检查</button> <button onclick="document.getElementById('movie').playbackRate=1">正常速度</button></p>
<p><a href="earth_orbit.blend">打开 Blender 场景</a> · <a href="README_验收说明.md">操作与限制</a> · <a href="delivery_verification.json">全部帧与视频检查</a> · <a href="verification.json">场景与开关验证</a></p>
<p><strong>本轮范围：</strong>固定 2020-10-29 16:40 UTC 附近真实天气，专门检查相机运动；不是天气延时。新的 Cycles 体积候选不是此前 GLSL 大气的完全移植。白天实际彩色覆盖限已备 GOES16/17，其他区域是明确的 IR 显示回退。源数据质量、全球原生细节和完整三维云不在本轮验收范围。</p>'''
    for frame,title in phases:
        html += f'<section><h2>{title} / 第 {frame} 帧</h2><div class="row">'
        for prefix,label in [('full','大气与气辉开启'),('no_airglow','只关闭气辉'),('no_atmosphere','全部关闭')]:
            html += f'<div><p>{label}</p><a href="comparisons/{prefix}_{frame:04d}.png"><img src="comparisons/{prefix}_{frame:04d}.png"></a></div>'
        html += '</div><small>同机位实际重渲染，点击原图检查；不对气辉差异图人工提亮冒充成片。</small></section>'
    html += '<h2>连续镜头总览</h2><img src="02_连续镜头总览.jpg"><p>请重点查看：近景厚度、晨昏颜色、夜间气辉强度、边缘是否跳动或断层。软件美术观感仍需你验收。</p>'
    html += '<h2>4K 地平线与自由相机</h2>'
    for name,label in [(f'4k_full_{round(count*.27):04d}.png','4K 白天地平线'),(f'4k_full_{count:04d}.png','4K 夜侧地平线'),(f'independent_free_camera_{round(count*.27):04d}.png','独立新建相机 / 新机位与50mm镜头')]:
        html += f'<p>{label} · <a href="comparisons/{name}">打开原图</a></p><a href="comparisons/{name}"><img src="comparisons/{name}"></a>'
    html += '<p>独立黑球气辉遮挡诊断是合成测试夹具，未当作卫星观测成片展示。源PNG和输出PNG均保持可追溯。</p>'
    (root/'index.html').write_text(html,encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='frames'},indent=2))


if __name__ == '__main__':
    main()
