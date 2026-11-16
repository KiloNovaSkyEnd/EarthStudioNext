"""Prepare a separate V3 delivery; never overwrite a finalized export."""
from pathlib import Path
import json
import shutil

root = Path(__file__).resolve().parents[1]
out = root/'data/exports/H9_20261020T2240_Blender_v3'
out.mkdir(exist_ok=False)
work = root/'data/blender_atmosphere_v3_work'
old = root/'data/exports/H9_20261020T2240_Blender_v2'
shutil.copytree(work/'assets', out/'assets')
shutil.copy2(work/'Atmosphere_review.blend', out/'Earth_Studio_分层大气版.blend')
for name in ['native_master.json', 'camera_bundle.json', 'package_manifest.json']:
    shutil.copy2(old/name, out/name)
preview = out/'效果对照'
preview.mkdir()
for name in ['old_blue', 'new_blue', 'new_richer', 'reference_angle']:
    shutil.copy2(root/'reports/layered_atmosphere_v3'/f'{name}.png', preview/f'{name}.png')
(out/'先看这里.md').write_text('''# V3 分层大气版

打开 **Earth_Studio_分层大气版.blend**，保留旁边的 **assets** 文件夹。已在 Blender 5.2.1 测试，不需要插件或自动运行脚本。本版以已保存的 V2 为基础，不包含你当前窗口中尚未保存的修改，也不会覆盖原工程。

## 先这样试

1. 默认是03侧视转俯视分镜。右侧扳手面板可调中文参数；若面板空白，在右上对象列表选择 **01｜运镜参数**。
2. **蓝色大气浓度=1、厚度=1** 是新版默认。更厚重可以试 **1.4、1.2**；更轻可以试 **0.8、0.9**。浓度控制显著程度，厚度控制外延和掠射空气感。直接输入数字即可。
3. **蓝色大气**、**夜间气辉** 两个复选框继续独立生效，支持单开、全开、全关。每个分镜独立设置。夜间气辉仍受夜侧位置影响。
4. F12渲染当前帧；播放时间轴检查运动。Eevee首次编译大纹理材质需要等待，首次加载可能达到约一分钟。

效果对照文件夹内 old_blue 与 new_blue 是相同镜头的旧版/新版实际渲染；new_richer 是浓度1.4、厚度1.2；reference_angle 是额外斜向镜头，方便检查轮廓层次。它们是1280×720检查图，工程仍引用16块原生纹理。

## 改运镜与动画

顶部“场景”下拉切换五个分镜，各有独立相机、控制器动画和输出范围。先暂停并选择帧，再调整参数；要保留动画修改，点击改过的参数右侧菱形，或悬停输入栏按I。换帧会恢复未写入关键帧的动画值。Ctrl+Z撤回，Ctrl+Shift+Z重做是Blender默认快捷键。

Graph Editor可继续改曲线；Dope Sheet可移动关键帧。整体变速需同时缩放当前控制器的全部关键帧时间，再调整结束帧，只改结束帧不会自动变速。新增浓度/厚度也可插入关键帧。

## 素材与本次修改

本次加强外缘和地平线内侧的淡蓝空气感；用解析相机射线的显示材质替换透明混合壳，减少Eevee透明抖动颗粒，没有对卫星云图做模糊或降噪。原卫星文件和五条运镜保留。参考的是你给出的画面观感，不能据此声称复现了参考作者的算法。

这是美术化大气显示近似，不是大气反演或物理散射模拟。原素材依然是2026-10-20 22:40 UTC单景H9观测（扫描至22:50），云图静止，非全球天气动画；未观测半球为灰色。红光原生22000×22000约500m，颜色1km、IR2km。输出分辨率和素材分辨率是不同概念。

verification保存实际检查结果；delivery_checksums.json记录交付文件哈希。本版未重新验收整个下载至全球时序生产链路。
''', encoding='utf-8')
print(out)
