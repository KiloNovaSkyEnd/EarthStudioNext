"""Verify immutable native assets and collect tested delivery evidence."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable

root = Path(__file__).resolve().parents[1]
package = require_writable(root/'data/exports/H9_20261020T2240_Blender_v1')
if (package/'delivery_checksums.json').exists():
    raise FileExistsError('Finalized delivery preserved')
manifest = json.loads((package/'package_manifest.json').read_text(encoding='utf-8'))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


for item in manifest['files']:
    assert digest(package/item['path']) == item['sha256']
reports = [root/'reports/blender_native_projection_verification.json',
           root/'reports/blender_native_scene_camera_verification.json',
           root/'reports/blender_native_image_verification.json',
           root/'reports/blender_native_portable/portable_verification.json']
projection, cameras, pixels, portable = [json.loads(p.read_text(encoding='utf-8')) for p in reports]
assert projection['visibility_matches_proj'] and cameras['weather_materials_included']
assert pixels['renders_verified'] == 10 and portable['all_images_inside_copied_package']
folder = package/'verification'
folder.mkdir(exist_ok=True)
for path in reports:
    shutil.copy2(path, folder/path.name)
from PIL import Image
import numpy as np
missing = np.asarray(Image.open(root/'reports/blender_native_portable/unobserved_side.png').convert('RGB'))
assert np.ptp(missing[60:120, 140:180].astype(int), axis=2).max() == 0
assert missing[90, 160].tolist() == [22, 22, 22]
(folder/'missing_side_pixel_check.json').write_text(json.dumps(dict(center_rgb=[22, 22, 22], interior_is_neutral=True, no_backside_weather_leak=True)), encoding='utf-8')
for source, name in [('take_A_start.png', 'preview_side.png'), ('take_A_nadir.png', 'preview_nadir.png'), ('native_detail_1080p.png', 'preview_native_detail.png')]:
    shutil.copy2(root/'reports/blender_native_bridge'/source, package/name)
bundle = json.loads((package/'camera_bundle.json').read_text(encoding='utf-8'))
rows = '\n'.join('| '+t['name']+' | '+str(t['samples'][-1]['seconds'])+'秒 | 1–'+str(math.ceil(1+t['samples'][-1]['seconds']*30))+' |' for t in bundle['tracks'])
readme = '''# Blender 静态原生圆盘验收工程

用 Blender 打开 **Earth_Native_Editable_v1.blend**。请整体保留本目录和 **assets** 文件夹，纹理采用相对路径；可离线移动，无需网页、Codex或科学Python环境。首次材质加载和编译需要等待。

## 本次包含

2026-10-20 22:40 UTC的Himawari-9原始圆盘GeoColor，红光网格22000×22000。颜色1km、IR2km；单星可见半球，灰色为无观测区域。2016年500m静态夜光在Satpy配方内，不另叠灯。

两条同名原分镜来自先前已备份的用户工程；A/B/C是测试镜头。当前网页未被重载或覆盖，最新未提交编辑不在这些相机关键帧中。五个分镜使用独立参数控制器和动画。

## 操作

1. 数字小键盘0进入相机视图；播放时间轴看运镜，F12渲染。默认输出1920×1080，可改4K。
2. 在场景相机栏选择对应分镜的“可编辑相机”，并按下表设置渲染范围。默认场景结束帧901，较短分镜之后会保持最后姿态。
3. 在Outliner选择该分镜“参数控制器”，物体属性→自定义属性修改targetLon/targetLat（目标经纬度）、heading（绕行）、pitch（俯看）、rangeKm（距离）、roll（画面旋转）、fov（垂直画角）。动画改值后插入关键帧，否则换帧会恢复动画值。
4. Graph Editor修改参数曲线、速度手柄或时间位置。缩放片长时仅选当前控制器的曲线，绕第1帧缩放时间。其他分镜不受影响。
5. 场景属性→自定义属性的 **blueAtmosphere** 和 **nightAirglow** 为独立开关，可以单开、全开、全关。太阳按观测UTC固定在世界坐标。

| 分镜 | 时长 | 渲染帧范围（30fps） |
| --- | --- | --- |
'''+rows+'''

## 测试结果和限制

已完成：原始纹理哈希核验、2709地理点投影对照、五套相机逐样本对照和编辑隔离、10张实际OptiX渲染、大气四组合、690个近景像素原生对照。工程已物理复制到其他目录，在禁用自动运行脚本的情况下重新打开并渲染；无观测半球为中性灰，不透出背面天气。见verification目录。

**天气只有一个观测时次，云图静止；相机动画可以连续播放。** 大气是柔和显示模型，不是实测气辉或物理体积散射。用户视觉质量仍待验收。

软件内一键导出、分镜自动批量渲染、连续天气、多星全球覆盖、Blender回传Cesium尚未完成。本目录是开发验收交付，不代表这些功能已完成。

delivery_checksums.json记录交付文件SHA256；blend内文本块也保留源工程、素材清单和操作说明。
'''
(package/'README.zh-CN.md').write_text(readme, encoding='utf-8')
files = [dict(path=p.relative_to(package).as_posix(), bytes=p.stat().st_size, sha256=digest(p)) for p in sorted(package.rglob('*')) if p.is_file()]
receipt = dict(schema='earthstudio.delivery_checksums.v1', files=files, totalBytes=sum(p['bytes'] for p in files), staticWeather=True)
(package/'delivery_checksums.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(package=str(package), files=len(files), totalBytes=receipt['totalBytes'], verified=True)), flush=True)
