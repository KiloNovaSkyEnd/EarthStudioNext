"""V2 native Blender usability: per-take scenes + Chinese modifier controls.

No add-on, autorun script, frame handler or external runtime needed after save.
Run with V1 blend loaded; always save to a new independent delivery folder.
"""
import json
import math
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from scripts.blender_support.editable_camera import PARAMETERS, curves

MODIFIER = '运镜与大气 · 在这里调整'
LABELS = ('目标经度（度）', '目标纬度（度）', '绕目标角度（度）', '俯看角度（度）', '距目标（公里）', '画面旋转（度）', '垂直画角（度）')
LIMITS = ((-36000, 36000), (-89, 89), (-36000, 36000), (-90, -2), (100, 50000), (-36000, 36000), (10, 110))


def retarget_drivers(owner, before, after, paths):
    if not owner.animation_data:
        return
    for curve in owner.animation_data.drivers:
        for variable in curve.driver.variables:
            for target in variable.targets:
                if target.id == before:
                    target.id = after
                    target.data_path = paths.get(target.data_path, target.data_path)


def modifier_controls(old, title, settings):
    mesh = bpy.data.meshes.new(title+' · 无可见几何')
    control = bpy.data.objects.new('01｜运镜参数 · '+title, mesh)
    for collection in old.users_collection:
        collection.objects.link(control)
    control.hide_render = True
    group = bpy.data.node_groups.new(title+' · 中文参数', 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    input_node, output_node = group.nodes.new('NodeGroupInput'), group.nodes.new('NodeGroupOutput')
    group.links.new(input_node.outputs['Geometry'], output_node.inputs['Geometry'])
    modifier = control.modifiers.new(MODIFIER, 'NODES')
    modifier.node_group = group
    modifier.show_group_selector = False
    modifier.show_manage_panel = False
    paths = {}
    sockets = []
    for parameter, label, limits in zip(PARAMETERS, LABELS, LIMITS):
        socket = group.interface.new_socket(name=label, in_out='INPUT', socket_type='NodeSocketFloat')
        socket.default_value = float(old[parameter])
        socket.min_value, socket.max_value = limits
        socket.description = label+'；动画改值后请在此栏插入关键帧'
        sockets.append(socket)
        getattr(modifier.properties.inputs, socket.identifier).value = float(old[parameter])
        paths['["'+parameter+'"]'] = f'modifiers["{MODIFIER}"].properties.inputs.{socket.identifier}.value'
    for key, label in [('blueAtmosphere', '蓝色大气'), ('nightAirglow', '夜间气辉')]:
        socket = group.interface.new_socket(name=label, in_out='INPUT', socket_type='NodeSocketBool')
        socket.default_value = bool(settings.get(key, True))
        sockets.append(socket)
        getattr(modifier.properties.inputs, socket.identifier).value = socket.default_value
        paths['["'+key+'"]'] = f'modifiers["{MODIFIER}"].properties.inputs.{socket.identifier}.value'
    # Blender dims unused modifier inputs. Make all inputs participate in a
    # harmless, render-hidden point inside Earth, so the native UI stays clear.
    for link in list(group.links):
        group.links.remove(link)
    total = None
    for socket in sockets:
        add = group.nodes.new('ShaderNodeMath')
        add.operation = 'ADD'
        if total is not None:
            group.links.new(total, add.inputs[0])
        group.links.new(input_node.outputs[socket.name], add.inputs[1])
        total = add.outputs[0]
    scale = group.nodes.new('ShaderNodeMath')
    scale.operation = 'MULTIPLY'
    scale.inputs[1].default_value = 1e-8
    group.links.new(total, scale.inputs[0])
    position = group.nodes.new('ShaderNodeCombineXYZ')
    group.links.new(scale.outputs[0], position.inputs[0])
    point = group.nodes.new('GeometryNodePoints')
    point.inputs['Count'].default_value = 1
    point.inputs['Radius'].default_value = 1e-8
    group.links.new(position.outputs[0], point.inputs['Position'])
    group.links.new(point.outputs['Points'], output_node.inputs['Geometry'])
    control.animation_data_create()
    control.animation_data.action = old.animation_data.action.copy()
    control.animation_data.action_slot = control.animation_data.action.slots[0]
    for curve in curves(control):
        curve.data_path = paths[curve.data_path]
    control['earthstudio_editable_track'] = old['earthstudio_editable_track']
    control['earthstudio_parameter_paths'] = json.dumps(paths)
    for obj in list(bpy.data.objects):
        retarget_drivers(obj, old, control, paths)
        if obj.type == 'CAMERA':
            retarget_drivers(obj.data, old, control, paths)
    bpy.data.objects.remove(old, do_unlink=True)
    return control, paths


def main():
    target = require_writable(sys.argv[sys.argv.index('--')+1])
    if target.exists():
        raise FileExistsError('Existing delivery is preserved')
    root = target.parent
    bundle = json.loads(bpy.data.texts['camera_bundle.json'].as_string())
    source = bpy.context.scene
    source_shell = next(o for o in source.objects if o.name.startswith('Soft atmosphere'))
    globe = next(o for o in source.objects if o.name.startswith('WGS84 Earth'))
    weather = bpy.data.collections.new('02｜天气地球 · 原始圆盘（无需修改）')
    weather.objects.link(globe)
    globe.hide_select = True
    archive = bpy.data.collections.new('90｜高级对照 · 默认隐藏')
    for obj in list(source.objects):
        if obj.type == 'CAMERA' and 'earthstudio_editable_camera' not in obj:
            archive.objects.link(obj)
            obj.hide_select = True
    scenes = []
    titles = ['原分镜一', '原分镜二', '侧视转俯视', '旋转推进', '同路径慢放']
    for index, track in enumerate(bundle['tracks']):
        identity = track['keyframeTrack']['id']
        title = titles[index] if index < len(titles) else track['name']
        seconds = track['samples'][-1]['seconds']
        camera = next(o for o in source.objects if o.get('earthstudio_editable_camera') == identity)
        old = bpy.data.objects[camera['earthstudio_controller']]
        collection = old.users_collection[0]
        collection.name = f'01｜调运镜 · {index+1:02d} {title}'
        control, paths = modifier_controls(old, title, dict(blueAtmosphere=source['blueAtmosphere'], nightAirglow=source['nightAirglow']))
        camera['earthstudio_controller'] = control.name
        camera.name = f'输出相机 · {index+1:02d} {title}'
        helpers = bpy.data.collections.new('辅助结构 · 自动驱动，无需手调 · '+title)
        collection.children.link(helpers)
        for obj in list(collection.objects):
            if obj != control:
                helpers.objects.link(obj)
                collection.objects.unlink(obj)
                obj.hide_select = True
        scene = source.copy()
        scene.use_fake_user = True
        scene.name = f'{index+1:02d}｜{title} · {seconds:g}秒'
        for child in list(scene.collection.children):
            scene.collection.children.unlink(child)
        for obj in list(scene.collection.objects):
            scene.collection.objects.unlink(obj)
        scene.collection.children.link(collection)
        scene.collection.children.link(weather)
        scene.collection.children.link(archive)
        effects = bpy.data.collections.new('03｜大气 · 开关在运镜参数中 · '+title)
        scene.collection.children.link(effects)
        shell = source_shell.copy()
        shell.name = '大气显示 · '+title
        shell.hide_select = True
        material = source_shell.data.materials[0].copy()
        shell.material_slots[0].link = 'OBJECT'
        shell.material_slots[0].material = material
        effects.objects.link(shell)
        # Each take has its own atmosphere toggles; all scenes share native images.
        for fcurve in material.node_tree.animation_data.drivers:
            for variable in fcurve.driver.variables:
                for item in variable.targets:
                    if item.id == source:
                        old_path = item.data_path
                        item.id_type = 'OBJECT'
                        item.id = control
                        item.data_path = paths[old_path]
        scene.camera = camera
        scene.frame_start, scene.frame_end = 1, math.ceil(1+seconds*30)
        scene.use_preview_range = False
        scene.render.filepath = f'//renders/{index+1:02d}_{title}/frame_'
        scene['earthstudio_scene_track'] = identity
        for key in ('blueAtmosphere', 'nightAirglow'):
            if key in scene:
                del scene[key]
        for marker in list(scene.timeline_markers):
            scene.timeline_markers.remove(marker)
        for i, key in enumerate(track['keyframeTrack']['keys']):
            scene.timeline_markers.new(f'关键帧{i+1} · {key["time"]:g}秒', frame=round(1+key['time']*30))
        layer = scene.view_layers[0]
        layer.layer_collection.children[archive.name].exclude = True
        layer.objects.active = control
        for obj in layer.objects:
            obj.select_set(obj == control, view_layer=layer)
        scene.frame_set(1)
        scenes.append(scene)
    initial = scenes[min(2, len(scenes)-1)]
    for window in bpy.context.window_manager.windows:
        window.scene = initial
    bpy.data.scenes.remove(source)
    if bpy.context.window:
        bpy.context.window.scene = initial
    print('SAVED_SCENES', [(s.name, s.users) for s in bpy.data.scenes], flush=True)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.overlay.show_overlays = False
                space.show_gizmo = False
                space.region_3d.view_perspective = 'CAMERA'
                space.region_3d.view_camera_zoom = 15
                space.shading.type = 'MATERIAL'
                space.shading.use_scene_world = True
            elif area.type == 'PROPERTIES':
                area.spaces.active.context = 'MODIFIER'
    for camera in bpy.data.cameras:
        camera.passepartout_alpha = 1
    for image in bpy.data.images:
        if image.source == 'FILE':
            destination = root/'assets'/Path(bpy.path.abspath(image.filepath)).name
            if not destination.is_file():
                raise FileNotFoundError(destination)
            image.filepath = '//assets/'+destination.name
    guide = '''上手只需三步：\n
1. 顶部“场景”下拉选分镜，镜头和播放/渲染范围一起切换。\n
2. 右侧扳手面板直接调中文运镜参数和两个大气开关。若换分镜后面板空白，在Outliner点该分镜的“01｜运镜参数”。\n
3. 播放时间轴看运镜，F12渲染；改动画参数后在输入栏右键→插入关键帧，或在该栏按I。换帧会读取已保存的动画值。\n
画面旋转就是横滚，单位度；垂直画角控制透视。Graph Editor可修改速度和时间。\n
辅助相机与源关键帧都保留在“90｜高级对照”集合，默认排除；辅助结构只驱动相机，无需逐个修改。\n
天气仍为22:40 UTC单景静态素材，云图不随时间变化。请整体保留assets目录。无需安装插件或开启自动运行脚本。\n'''
    bpy.data.texts.new('00｜从这里开始 · 三步操作.txt').write(guide)
    for name in list(bpy.data.texts.keys()):
        if name.startswith('START_HERE'):
            bpy.data.texts[name].clear()
            bpy.data.texts[name].write(guide)
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target), relative_remap=False)
    print('BEGINNER_WORKSPACE_READY', str(target), flush=True)


if __name__ == '__main__':
    main()
