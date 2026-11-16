"""New 11K one-texture template; preserve every original22K scene and file."""
import json
import hashlib
import os
from pathlib import Path
import sys

import bpy

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from ges_next.isolation import require_writable
from scripts.blender_support.layered_atmosphere import create
from scripts.blender_import_dynamic_cameras import gap_hold_expression

package = root / 'data/exports/H9_20261020_12h_Blender_11K_v1'
pilot = '--pilot' in sys.argv
target = require_writable(package / ('Earth_Studio_11K_小样_v3.blend' if pilot else 'Earth_Studio_11K_清晰构图版.blend'))
if target.exists():
    raise FileExistsError('Existing compact template preserved')
sequence = json.loads((package / ('pilot_manifest.json' if pilot else 'sequence_manifest.json')).read_text(encoding='utf-8'))
assert len(sequence['files']) == (3 if pilot else 73) and all((package / f['path']).stat().st_size == f['bytes'] for f in sequence['files'])
source = json.loads((root / 'data/exports/H9_20261020_12h_Blender_v1/native_master.json').read_text(encoding='utf-8'))
first = source['tiles'][0]
left, top = first['extent'][0], first['extent'][3]
dx, dy = first['transform'][0] * 2, first['transform'][4] * 2
master = dict(shape=[11000, 11000], source_shape=[22000, 22000], tiles=[dict(
    path='disk.png', shape=[11000, 11000], crs=first['crs'],
    extent=[left, top + dy * 11000, left + dx * 11000, top],
    transform=[dx, 0, left, 0, dy, top, 0, 0, 1],
    coreWindow=dict(row=0, col=0, sourceX=0, sourceY=0, width=11000, height=11000))])
(package / 'native_master.json').write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding='utf-8')
image = bpy.data.images.load(str(package / 'assets/disk/weather_0001.png'), check_existing=False)
image.name = '11K圆盘 · 73节点 · 无损PNG编码'
source_video = root / 'data/cesium_h9_motion_20261020/timelapse_1d4aba570d913124.mp4'
video_file = package / 'assets/video/timelapse.mp4'
video_file.parent.mkdir(exist_ok=True)
if not video_file.exists():
    os.link(source_video, video_file)
assert hashlib.sha256(video_file.read_bytes()).hexdigest() == '3bce241bf2cf6b418a8e0f0e008e64c6bc71d2b3daca3803e84d1a420165b18a'
video = bpy.data.images.load(str(video_file), check_existing=False)
video.name = '流畅编辑预览 · 4096×2048 · 正式渲染不用此视频'
video.source = 'MOVIE'
sequence['auxiliary_files'] = [dict(path=video_file.relative_to(package).as_posix(),bytes=video_file.stat().st_size,sha256=hashlib.sha256(video_file.read_bytes()).hexdigest())]
if not pilot:
    (package / 'sequence_manifest.json').write_text(json.dumps(sequence,ensure_ascii=False,indent=2),encoding='utf-8')
old_materials, old_meshes = set(), set()
for scene in bpy.data.scenes:
    bpy.context.window.scene = scene
    control = bpy.data.objects[scene.camera['earthstudio_controller']]
    paths = json.loads(control['earthstudio_parameter_paths'])
    modifier = control.modifiers[0]
    modifier.node_group = modifier.node_group.copy()
    group = modifier.node_group
    socket = group.interface.new_socket(name='预览使用11K细节（较慢）', in_out='INPUT', socket_type='NodeSocketBool')
    socket.default_value = True
    socket.description = '默认暂停看11K；取消勾选可使用轻量视频。正式渲染始终使用11K素材。'
    preview_path = f'modifiers["{modifier.name}"].properties.inputs.{socket.identifier}.value'
    paths['["previewHigh"]'] = preview_path
    control['earthstudio_parameter_paths'] = json.dumps(paths)
    input_node = next(n for n in group.nodes if n.bl_idname=='NodeGroupInput')
    scale = next(n for n in group.nodes if n.bl_idname=='ShaderNodeMath' and n.operation=='MULTIPLY' and abs(n.inputs[1].default_value-1e-8)<1e-12)
    add = group.nodes.new('ShaderNodeMath');add.operation='ADD'
    group.links.new(scale.inputs[0].links[0].from_socket,add.inputs[0])
    group.links.new(input_node.outputs[socket.name],add.inputs[1]);group.links.new(add.outputs[0],scale.inputs[0])
    getattr(modifier.properties.inputs,socket.identifier).value=True
    old = next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
    owners = list(old.users_collection)
    old_materials.update(old.data.materials)
    old_meshes.add(old.data)
    shell = create(scene, master, package / 'assets', {'disk.png': image}, dict(vectors=sequence['suns']), control, paths)
    initial_collections = list(shell.users_collection)
    for collection in owners:
        if shell.name not in collection.objects:
            collection.objects.link(shell)
    for collection in initial_collections:
        if collection not in owners:
            collection.objects.unlink(shell)
    bpy.data.objects.remove(old, do_unlink=True)
    for node in shell.data.materials[0].node_tree.nodes:
        if node.type != 'TEX_IMAGE':
            continue
        node.label = '11000×11000圆盘 · 从22K缩小 · PNG无损编码'
        user = node.image_user
        user.frame_start = 1
        user.frame_duration = 1000000
        user.use_auto_refresh = True
        driver = user.driver_add('frame_offset').driver
        variable = driver.variables.new()
        variable.name = 'hours'
        variable.targets[0].id = control
        variable.targets[0].data_path = paths['["weatherHours"]']
        driver.expression = gap_hold_expression(sequence['nodes'])
    proxy = create(scene,dict(projection='geographic_preview'),package/'assets',{'video':video},dict(vectors=sequence['suns']),control,paths)
    del proxy['earthstudio_layered_atmosphere']
    proxy['earthstudio_preview_proxy'] = True
    proxy.name = '编辑预览 · 连续云图视频 · 不参与正式渲染 · '+scene.name
    proxy.hide_render = True
    for collection in owners:
        if proxy.name not in collection.objects:collection.objects.link(proxy)
    for collection in list(proxy.users_collection):
        if collection not in owners:collection.objects.unlink(proxy)
    for obj,expression in [(shell,'not high'),(proxy,'high')]:
        driver = obj.driver_add('hide_viewport').driver
        variable = driver.variables.new();variable.name='high'
        variable.targets[0].id=control;variable.targets[0].data_path=preview_path
        driver.expression=expression
    for node in proxy.data.materials[0].node_tree.nodes:
        if node.type!='TEX_IMAGE':continue
        user=node.image_user;user.frame_start=1;user.frame_duration=1000000;user.use_auto_refresh=True
        driver=user.driver_add('frame_offset').driver
        variable=driver.variables.new();variable.name='hours'
        variable.targets[0].id=control;variable.targets[0].data_path=paths['["weatherHours"]']
        driver.expression=gap_hold_expression(sequence['nodes'])
    scene['weather_gap_display_policy']='hold-last-labeled'
    scene['weather_missing_nodes']=json.dumps([node for node in sequence['nodes'] if node['missing']])
    scene['earthstudio_texture_mode'] = '11000 display derivative; one RGBA sequence; area reduction from22K'
    scene.sync_mode = 'FRAME_DROP'
    scene.render.use_simplify = False
    scene.render.use_texture_cache = False
    scene.render.use_auto_generate_texture_cache = False
    scene.frame_set(1)
for mesh in old_meshes:
    if not mesh.users:
        bpy.data.meshes.remove(mesh)
for material in old_materials:
    if not material.users:
        bpy.data.materials.remove(material)
for old in list(bpy.data.images):
    if old not in (image,video) and not old.users:
        bpy.data.images.remove(old)
image.source = 'SEQUENCE'
image.filepath = bpy.path.relpath(str(package / 'assets/disk/weather_0001.png'))
video.filepath = bpy.path.relpath(str(video_file))
assert Path(bpy.path.abspath(image.filepath)).is_file()
for text in ['native_master.json', 'sequence_manifest.json']:
    block = bpy.data.texts.get(text) or bpy.data.texts.new(text)
    block.clear()
    block.write(json.dumps(sequence,ensure_ascii=False,indent=2) if text=='sequence_manifest.json' else (package / text).read_text(encoding='utf-8'))
bpy.data.texts.new('00｜11K优化版说明.txt').write('''此为独立11K编辑/渲染版本，正式渲染使用一个全圆盘RGBA序列。
默认视口显示11K；用工具包启动可自动切换至4096×2048流畅播放视频，不参与正式渲染。
在01｜运镜参数中开启“预览使用11K细节（较慢）”可查看高细节，再关闭恢复编辑预览。
由已完成22K合成图作透明度加权2×2平均，降低空间细节；PNG编码本身无损。
不是重新从L1生成的未锐化1km配方，也不是全通道500米观测。
天气时刻、真实缺档、大气/气辉控制及相机关键帧保留。
支持继续修改运镜、焦距、天气速度和分镜。22K原模板及原生素材另行保留。
要恢复最高细节，请用原工具导入同一相机JSON；两版素材不混用。
''')
bpy.context.window.scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'USER')
bpy.ops.wm.save_as_mainfile(filepath=str(target), relative_remap=True)
assert Path(bpy.path.abspath(image.filepath)).resolve() == (package / 'assets/disk/weather_0001.png').resolve()
print('COMPACT_11K_TEMPLATE_SAVED', target, flush=True)
