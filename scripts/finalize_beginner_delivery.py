"""Collect V2 usability evidence and write a small user-facing start guide."""
import hashlib
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
out = root/'data/exports/H9_20261020T2240_Blender_v2'
if (out/'delivery_checksums.json').exists():
    raise FileExistsError('Finalized V2 is preserved')
assert (out/'Earth_Studio_新手版.blend').is_file()
result = json.loads((root/'reports/blender_beginner_workspace_verification.json').read_text(encoding='utf-8'))
assert len(result['scenes']) == 5 and result['independent_native_modifier_edit']
assert result['per_take_render_range'] and result['per_take_atmosphere']
evidence = out/'verification'
evidence.mkdir(exist_ok=True)
for path in [root/'reports/blender_beginner_workspace_verification.json',
             root/'reports/blender_beginner_renders/render_verification.json',
             root/'reports/blender_beginner_renders/pixel_verification.json']:
    shutil.copy2(path, evidence/path.name)
shutil.copy2(root/'reports/blender_beginner_workspace_ui.jpg', out/'界面示例.jpg')
(out/'先看这里.md').write_text('''# Blender 新手版：选分镜、调参数、看运镜

打开 **Earth_Studio_新手版.blend**。保留同目录的 **assets** 文件夹。适用于本机已验证的 Blender 5.2.1，无需安装插件或开启自动运行脚本。

## 三步操作

1. **选分镜**：顶部“场景”下拉选择01–05。相机、参数面板、播放和渲染范围会一起切换。默认展示03侧视转俯视分镜。
2. **调画面**：右侧扳手面板直接输入中文参数。画面旋转就是横滚；垂直画角控制透视。蓝色大气和夜间气辉两个复选框可以单开、全开或全关，每个分镜独立。
3. **看运镜**：播放时间轴；F12渲染当前帧。辅助相机默认隐藏，不会再以黑色三角形和交叉线挡住地球。

## 修改关键帧

先暂停，选择要修改的帧，再调整参数。在每个改过的输入栏右侧点菱形保存关键帧，也可悬停该栏按I或右键→插入关键帧。数值改动不会自动保存成关键帧；否则换帧时会恢复动画值。

Graph Editor可继续调整曲线和速度；Dope Sheet可移动关键帧。要整体变快/变慢，需要同时缩放当前控制器的全部动画关键帧时间，再修改结束帧。只改结束帧是裁切/延长范围，不会自动改变运镜速度。

若参数面板空白，在右上Outliner点该分镜的 **01｜运镜参数**。若不小心转离相机视图，把鼠标放到画面上按数字小键盘0；没有小键盘可用“视图→相机→活动相机”。

## 五个分镜

| 顶部场景 | 导入时长 | 自动帧范围 |
| --- | --- | --- |
| 01 原分镜一 | 10秒 | 1–301 |
| 02 原分镜二 | 20秒 | 1–601 |
| 03 侧视转俯视 | 20秒 | 1–601 |
| 04 旋转推进 | 12秒 | 1–361 |
| 05 同路径慢放 | 30秒 | 1–901 |

01/02来自先前备份的用户工程，03/04/05为验收演示。原V1和当前网页工程均未覆盖。每个分镜有独立输出目录 **renders/对应分镜/**，菜单“渲染→渲染动画”默认输出PNG序列；尚无一键批量MP4。

## 素材与限制

天气仍是 **2026-10-20 22:40 UTC单景**，云图静止，镜头可以运动。16块原生纹理完整保留，红光22000×22000约500m，颜色1km/IR2km。单星没有观测的半球为灰色，不补静态地表。

较大纹理首次加载/编译需要等待。已测试场景重开、各分镜全部相机样本、修改隔离、四种大气组合及实际Windows界面。verification目录包含报告，delivery_checksums.json包含交付哈希。
''', encoding='utf-8')
manifest = json.loads((out/'package_manifest.json').read_text(encoding='utf-8'))
for item in manifest['files']:
    with (out/item['path']).open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == item['sha256']
records = []
for path in sorted(out.rglob('*')):
    if path.is_file():
        with path.open('rb') as stream:
            records.append(dict(path=path.relative_to(out).as_posix(), bytes=path.stat().st_size,
                                sha256=hashlib.file_digest(stream, 'sha256').hexdigest()))
(out/'delivery_checksums.json').write_text(json.dumps(dict(files=records, totalBytes=sum(p['bytes'] for p in records)), ensure_ascii=False, indent=2), encoding='utf-8')
print('V2_DELIVERY_READY', len(records), 'files', flush=True)
