"""Export verified movies with encoded-frame QA and explicit source/model limits."""
import hashlib
import json
from pathlib import Path
import shutil
import imageio_ffmpeg
import numpy as np
from PIL import Image,ImageDraw
from ges.storage import load_config


def main():
    cfg=load_config();root=cfg.processed_dir/'goni_film_v1';rendered=root/'rendered_v2'
    report=json.loads((rendered/'verification.json').read_text())
    if report['stills_only'] or len(report['films'])!=3 or len(report['records'])!=31:raise ValueError('Complete three-view weather movies required')
    if any(r['material_revision']!=6 for r in report['records']):raise ValueError('Final daylight/spectral material required')
    target=cfg.export_dir/'goni_review_v1';target.mkdir(parents=True,exist_ok=True)
    def copy(source,dest):
        source=Path(source);dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and hashlib.sha256(dest.read_bytes()).digest()!=hashlib.sha256(source.read_bytes()).digest():
            # Preserve previous permanent exports on rerun rather than silently
            # replace a reviewed result with a different experiment.
            raise FileExistsError('Different permanent export already exists: '+str(dest))
        if not dest.exists():shutil.copy2(source,dest)
        if hashlib.sha256(dest.read_bytes()).digest()!=hashlib.sha256(source.read_bytes()).digest():raise IOError('Export checksum mismatch')
    sheet=Image.new('RGB',(1440,858),(8,13,22));draw=ImageDraw.Draw(sheet)
    views=['nadir','oblique','detail'];sample_indices={0:0,87:1,191:2};decoded=[]
    for col,view in enumerate(views):
        source=rendered/f'goni_{view}_8s.mp4';reader=imageio_ffmpeg.read_frames(str(source));meta=next(reader);count=0
        if meta['size']!=(1920,1080) or abs(meta['fps']-24)>.01:raise ValueError('Unexpected final movie geometry/rate')
        for index,data in enumerate(reader):
            count+=1
            if index in sample_indices:
                row=sample_indices[index];pixels=np.frombuffer(data,np.uint8).reshape(1080,1920,3)
                im=Image.fromarray(pixels).resize((480,270),Image.Resampling.LANCZOS)
                sheet.paste(im,(col*480,row*286+16));draw.text((col*480+8,row*286+2),view+' | '+['04:00 daytime','08:40 transition','14:00 night'][row]+' UTC',fill='white')
        if count!=192:raise ValueError('Encoded contact-sheet decode count failed')
        decoded.append({'view':view,'decoded_frames':count,'sample_frame_indices':list(sample_indices)})
        copy(source,target/source.name)
    sheet.save(rendered/'encoded_contact_sheet.png');copy(rendered/'encoded_contact_sheet.png',target/'encoded_contact_sheet.png')
    for source in rendered.glob('*.png'):copy(source,target/'images'/source.name)
    for source in (root/'diagnostics_v2').glob('evidence_*.png'):copy(source,target/'images'/source.name)
    for source in (root/'references').glob('*.png'):copy(source,target/'references'/source.name)
    # Describe count semantics accurately: the original partial-tint counter
    # includes nominal low clouds and ROI-feathered strict low-cloud pixels.
    for record in report['records']:
        evidence=record.get('lowcloud_evidence') or {}
        if 'nominal_uncertain_low_pixels' in evidence:
            evidence['nominal_or_roi_feathered_low_tint_pixels']=evidence.pop('nominal_uncertain_low_pixels')
    report['cloud_lighting']+='; night normal contrast is a fixed display direction, not measured lunar illumination'
    report['volume_control']='LEFT max0.25km thin cloud column, RIGHT max0.8km column; both retain retrieved display heights, so this is thickness control, not an absence-of-height test'
    report['encoded_contact_sheet_verification']=decoded
    report['export_directory']=str(target.resolve())
    (target/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    copy(Path('docs/GONI_FILM.md'),target/'processing_notes.md')
    note='''# 天鹅真实时序审阅样片

2020-10-30 04:00–14:00 UTC，31个真实AHI扫描、20分钟间隔。三片各8秒、
1920×1080、24fps、192显示帧；重复帧不是新增观测，没有合成中间天气。

夜间蓝色低云使用同一时次的液态/过冷水相态、云高/误差及质量筛选，
长波/短波差异恢复实测纹理；分类失败不会清空其他云。云概率和相态改进区
为原生行1200:2600、列1600:3400，外部保留早期VIS/IR，不能称为全球改进。
白天将实测反射率影调与模型透明度分开，使用近似云体自阴影、投影云影及
有上限的弱海面反射。没有生成云图、强太阳圆斑或伪造夜间可见光。

这是审阅样片，尚未达到近100%参考匹配。实测云顶不等于完整三维反演；
云底、厚度、消光和夜间法线照明为显示假设，海况未实测。源IR原生2km，
蓝色是显示色；静态地表2004年、灯光2016年。尚未整合到Blender/桌面应用。
体积对照左侧为0.25km薄云柱，右侧为最高0.8km厚云柱，两侧都保留显示云高。

185项测试通过；三个视频均完整解码确认192帧。encoded_contact_sheet.png
来自编码后的视频帧0/87/191，对应04:00、08:40、14:00 UTC。测试不代表审美验收。
原批次原始资料4,973,891,895字节；新增必要B07补充171,286,780字节，合计
5,145,178,675字节。新批次单独预检，不把合计宣称为低于5GB。
'''
    (target/'README_zh.md').write_text(note,encoding='utf-8')
    cards=''.join(f'<section><h2>{title} · 8秒</h2><video controls loop preload="metadata" src="goni_{view}_8s.mp4"></video></section>' for view,title in zip(views,['俯视','斜视','近景正面']))
    pairs=''.join(f'<details><summary>{title}</summary><img src="images/{name}.png"></details>' for title,name in [
        ('白天：旧硬掩膜与新材质（相同新照明）','material_0400'),('夜间：旧灰度与恢复低云（相同新照明）','material_1400'),
        ('昼夜过渡：云厚度0.25km / 0.8km','volume_0840'),('夜间：气辉关闭 / 开启','airglow_1400'),
        ('夜间低云相态与云高支持检查','evidence_1400')])
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>天鹅 · 日夜云图审阅</title>
<style>body{max-width:1440px;margin:24px auto;padding:0 18px;background:#09111d;color:#d9e5f1;font:16px/1.7 system-ui}a{color:#9edafa}video,img{width:100%;display:block}section{margin:32px 0}details{margin:16px 0;padding:12px;background:#121e2d}summary{cursor:pointer}small{color:#9fb0c5}</style>
<h1>天鹅：真实时序审阅样片</h1><p>2020-10-30 04:00–14:00 UTC · 31次实际观测 · 20分钟间隔 · 三种固定视角</p>
<p>各8秒，1080p / 24fps；以重复帧播放实际观测，没有生成中间天气。已恢复夜间相态/云高约束的蓝色低云与实测双通道纹理，并将白天反射率影调和模型透明度分开。</p>
<p><strong>仍是审阅版本：</strong>未达到近100%参考匹配；云底、厚度、消光、夜间法线光照及海面粗糙度为显示假设，源IR细节上限为2km，相态与云概率改进限于天鹅区域。</p>
<p><a href="README_zh.md">结果与限制</a> · <a href="processing_notes.md">处理方案</a> · <a href="verification.json">来源/UTC/完整解码核验</a></p>
<h2>编码后视频抽帧对照</h2><img src="encoded_contact_sheet.png">'''+cards+'<h2>控制与证据对照</h2>'+pairs+'''
<h2>用户视觉参考（其他台风事件）</h2><details><summary>白天参考</summary><img src="references/reference_day.png"></details><details><summary>夜间参考</summary><img src="references/reference_night.png"></details><details><summary>昼夜过渡参考</summary><img src="references/reference_transition.png"></details></html>'''
    (target/'index.html').write_text(html,encoding='utf-8')
    print('EXPORTED',target,flush=True)


if __name__=='__main__':main()
