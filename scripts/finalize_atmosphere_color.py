"""Package V4 controls with evidence and immutable asset checks."""
import hashlib
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
out = root/'data/exports/H9_20261020T2240_Blender_v4'
seal = out/'delivery_checksums.json'
if seal.exists():
    raise FileExistsError('Finalized V4 preserved')
old = root/'data/exports/H9_20261020T2240_Blender_v3'
proof = root/'reports/atmosphere_color_v4'
data = json.loads((proof/'verification.json').read_text(encoding='utf-8'))
assert len(data['scenes']) == 5 and len(data['actual_render_controls']) == 10
assert data['separate_switches'] and data['disabled_controls_leave_surface_unchanged']
shutil.copytree(proof, out/'verification')
shutil.copy2(root/'reports/atmosphere_color_v4_camera.json', out/'verification/camera.json')
for name in ['native_master.json', 'camera_bundle.json', 'package_manifest.json']:
    shutil.copy2(old/name, out/name)
manifest = json.loads((out/'package_manifest.json').read_text(encoding='utf-8'))
for row in manifest['files']:
    with (out/row['path']).open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == row['sha256']
(out/'先看这里.md').write_text('''# 大气与气辉调色版 V4

打开 **Earth_Studio_大气与气辉调色版.blend**，保留旁边的assets文件夹。以已保存V3为基础，不包含你其他窗口里的未保存修改。原V3保留。

## 右侧面板怎么调

右上选择当前分镜的 **01｜运镜参数**，打开扳手面板。蓝色大气、夜间气辉两个复选框仍可独立开关；两层各有独立的五个数值参数，可直接输入，也可拖动数字。

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| 浓度 | 1 | 调整层的强弱；0完全去除该层 |
| 厚度 | 1 | 调整地平线附近范围；0.5–2 |
| 色相（度） | 0 | -180到180度偏移；0保留原颜色 |
| 饱和度 | 1 | 0变灰，低于1减淡，高于1更鲜艳；最高2 |
| 亮度 | 1 | 调整该层发光颜色，最高3；0变黑但仍保留该层遮光 |

**完全移除效果请关闭开关或将浓度设0，不要用亮度0代替关闭。** 夜间气辉受夜侧限制，白天方向可能不明显，这是正常的；不会为调色把气辉铺满白天。

先从浓度1.3、厚度1.2小幅增加；想更克制可把饱和度调到0.8。两层的色相与饱和度只调整附加效果，不给卫星云图整体染色。色相是相对于蓝色/暖色基色的偏移，不是绝对HSV色环位置。

## 动画与分镜

所有参数支持原生Blender关键帧：先选帧、改数值，悬停输入栏按I或点右侧菱形。换帧前记得保存关键帧。顶部场景下拉切换五个独立分镜，参数和动画互不覆盖。F12渲染当前帧。无需插件或开启自动运行脚本。

已验证五个分镜十项参数的关键帧回放、实际渲染响应、全关后的参数隔离和原运镜保留。verification内是640×360检查图与报告，不代表最终输出分辨率。仍使用原16块卫星纹理和单时刻2026-10-20 22:40 UTC的H9素材，未观测面为灰色；本次没有增加天气时序或改动科学配色。
''', encoding='utf-8')
records = []
for path in sorted(out.rglob('*')):
    if path.is_file():
        with path.open('rb') as stream:
            records.append(dict(path=path.relative_to(out).as_posix(), bytes=path.stat().st_size,
                                sha256=hashlib.file_digest(stream, 'sha256').hexdigest()))
seal.write_text(json.dumps(dict(project='Earth_Studio_大气与气辉调色版.blend', files=records), ensure_ascii=False, indent=2), encoding='utf-8')
print('V4_DELIVERY_READY', len(records), flush=True)
