"""Assemble a local review page from completed, actual rendered test movies."""
from pathlib import Path
import json
import imageio_ffmpeg
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'data/processed/atmosphere_scattering_v3'
    report = json.loads((folder / 'verification.json').read_text(encoding='utf-8'))
    metadata = []
    for film in report['films']:
        path = folder / film['file']
        reader = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgb24')
        info = next(reader)
        count = sum(1 for _ in reader)
        assert count == film['frames'], (path, count)
        assert tuple(info['size']) == tuple(report['output_dimensions'])
        assert abs(info['fps'] - film['fps']) < .01
        metadata.append({'file': path.name, 'decoded_frames': count,
                         'fps': info['fps'], 'seconds': count / info['fps'],
                         'size': info['size'], 'bytes': path.stat().st_size})
    (folder / 'video_validation.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    sheet = Image.new('RGB', (1280, 10 * 205), '#080c12')
    draw = ImageDraw.Draw(sheet)
    for row, name in enumerate(report['still_comparisons']):
        for col, state in enumerate(['off', 'on']):
            im = Image.open(folder / f'{name}_{state}.png').convert('RGB')
            im.thumbnail((640, 180))
            x, y = col * 640, row * 205
            sheet.paste(im, (x, y + 25))
            draw.text((x + 10, y + 7), f'{name} | atmosphere {state}', fill='white')
    for k, film in enumerate(report['films']):
        for j, frame in enumerate(film['keyframes']):
            im = Image.open(folder / (Path(film['file']).stem + f'_{frame:04d}.png')).convert('RGB')
            im.thumbnail((426, 240))
            row, col = divmod(j, 3)
            sheet.paste(im, (col * 426, 820 + k * 600 + row * 250))
    sheet.save(folder / 'review_contact_sheet.jpg', quality=94)
    comparisons = ''.join(
        f'<h3>{name}</h3><div class="pair"><figure><img src="{name}_off.png"><figcaption>关闭大气</figcaption></figure>'
        f'<figure><img src="{name}_on.png"><figcaption>单次散射与可选气辉开启</figcaption></figure></div>'
        for name in report['still_comparisons'])
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>轨道距离大气测试 v3</title>
<style>body{margin:32px auto;max-width:1400px;padding:0 20px;background:#0b1019;color:#e5edf6;font:17px/1.65 system-ui}h1,h2{line-height:1.3}video{width:100%;background:black}a{color:#91caff}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0}img{width:100%}figcaption{color:#bcc9d9}section{margin:40px 0}.note{border-left:3px solid #9fcaff;padding-left:16px}button{font:inherit;margin:10px 8px 10px 0;padding:6px 12px} @media(max-width:700px){.pair{grid-template-columns:1fr}}</style>
<h1>轨道距离大气测试 v3</h1>
<p>主运镜高度为距地面 <b>600–3000 公里</b>，不使用 40 公里近地镜头。光线沿大气体积积分，日夜共用同一套计算。</p>
<p class="note">这是独立 GPU 研究渲染器，尚未接入 Blender 主场景。云场冻结在 2020-10-29 16:40 UTC；极地仍缺测。大气采用标准密度近似，并非当时卫星反演。地表仍是现有 8192×4096 显示纹理，斜视仍受源分辨率及平面云层限制。</p>
<section><h2>固定镜头：白天到夜间</h2>
<p>30 秒、24 fps。仅太阳模拟时间从 14:40 走到 20:40 UTC，云形保持不动；这是照明连续性测试，不是真实天气延时。</p>
<video id="solar" controls preload="metadata" poster="fixed_camera_day_to_night_0360.png" src="fixed_camera_day_to_night.mp4"></video>
<button onclick="document.getElementById('solar').playbackRate=.5">半速检查</button><button onclick="document.getElementById('solar').playbackRate=1">正常速度</button></section>
<section><h2>斜视运镜：600 → 3000 → 600 公里</h2>
<p>30 秒、24 fps。固定实际参考 UTC，镜头向西移动约 70°，起止速度与加速度为零。检查地平线、斜视纹理、气辉与日侧的连续衔接。</p>
<video id="camera" controls preload="metadata" poster="grazing_terminator_flyby_0360.png" src="grazing_terminator_flyby.mp4"></video>
<button onclick="document.getElementById('camera').playbackRate=.5">半速检查</button><button onclick="document.getElementById('camera').playbackRate=1">正常速度</button></section>
<section><h2>同一镜头开关对照</h2><p>日侧镜头高度 600 / 1200 公里；暮光与夜侧镜头 1500 公里。关闭效果后可直接检查原始显示纹理。</p>''' + comparisons + '''</section>
<section><h2>验证与限制</h2><p>148 项单元测试通过；相同输入重复渲染逐像素一致。积分收敛和完整解码检查见下方 JSON。相邻帧差异包含真实运镜位移，不能直接等同闪烁。</p>
<p>尚无多次散射、实测气溶胶与真实云顶高度；此前源拼接色差仍存在，不能把该版本视为全球所有时间和路径已验收。</p>
<a href="verification.json">数值验证</a> · <a href="video_validation.json">影片完整解码结果</a> · <a href="review_contact_sheet.jpg">关键帧总览</a></section></html>'''
    (folder / 'review.html').write_text(html, encoding='utf-8')
    print(json.dumps(metadata, indent=2))
    print(folder / 'review.html')


if __name__ == '__main__':
    main()
