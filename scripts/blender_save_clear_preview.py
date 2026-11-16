"""Save an independent template with clear paused composition as native default."""
import json
import sys
from pathlib import Path
import bpy

target = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
if target.exists():
    raise FileExistsError(target)
for scene in bpy.data.scenes:
    camera = scene.camera
    control = bpy.data.objects.get(camera.get('earthstudio_controller', '')) if camera else None
    if not control:
        continue
    paths = json.loads(control.get('earthstudio_parameter_paths', '{}'))
    path = paths.get('["previewHigh"]')
    if path:
        owner, attribute = path.rsplit('.', 1)
        setattr(control.path_resolve(owner), attribute, True)
        control.update_tag()
        scene['earthstudio_preview_help'] = '默认11K细节；用Open_My_11K.cmd自动切换流畅播放，N侧栏Earth Studio选择模式。正式渲染始终11K。'
for block in bpy.data.texts:
    if '11K优化版说明' in block.name:
        block.clear()
        block.write('默认暂停构图显示11K PNG。流畅播放视频为4096×2048，细节较软。\n通过工具包启动可自动在暂停11K与播放视频之间切换，并显示当前画质标签。\n三维窗口按N，Earth Studio可锁定11K或视频。直接打开blend时可在运镜参数勾选/取消“预览使用11K细节”。\n正式渲染始终11K PNG，原22K素材及工程另行保留。\n11K是22K的透明度加权2×2缩小，有空间细节损失；PNG编码对缩小后的像素无损。\n')
bpy.ops.wm.save_as_mainfile(filepath=str(target), relative_remap=True)
print('CLEAR_PREVIEW_SAVED', target)
