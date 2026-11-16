"""Upgrade saved V2/V3 to independent V4 atmosphere color controls; preserve cameras."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from scripts.blender_support.layered_atmosphere import create, CONTROLS


def main():
    output = require_writable(sys.argv[sys.argv.index('--')+1])
    if output.exists():
        raise FileExistsError('Existing scene preserved')
    master = json.loads(bpy.data.texts['native_master.json'].as_string())
    manifest = json.loads(bpy.data.texts['package_manifest.json'].as_string())
    images = {Path(bpy.path.abspath(i.filepath)).name: i for i in bpy.data.images if i.source == 'FILE'}
    initial = bpy.context.window.scene
    for scene in list(bpy.data.scenes):
        bpy.context.window.scene = scene
        control = bpy.data.objects[scene.camera['earthstudio_controller']]
        paths = json.loads(control['earthstudio_parameter_paths'])
        modifier = control.modifiers[0]
        group = modifier.node_group
        input_node = next(n for n in group.nodes if n.bl_idname == 'NodeGroupInput')
        scale = next(n for n in group.nodes if n.bl_idname == 'ShaderNodeMath' and n.operation == 'MULTIPLY' and abs(n.inputs[1].default_value-1e-8) < 1e-12)
        total = scale.inputs[0].links[0].from_socket
        for key, label, minimum, maximum, default in CONTROLS:
            if '["'+key+'"]' in paths:
                continue
            socket = group.interface.new_socket(name=label, in_out='INPUT', socket_type='NodeSocketFloat')
            socket.default_value = default
            socket.min_value, socket.max_value = minimum, maximum
            socket.description = '色相0度、其他参数1为默认；仅调整附加大气/气辉，不改卫星素材'
            getattr(modifier.properties.inputs, socket.identifier).value = float(default)
            paths['["'+key+'"]'] = f'modifiers["{modifier.name}"].properties.inputs.{socket.identifier}.value'
            add = group.nodes.new('ShaderNodeMath')
            add.operation = 'ADD'
            group.links.new(total, add.inputs[0])
            group.links.new(input_node.outputs[socket.name], add.inputs[1])
            total = add.outputs[0]
        group.links.new(total, scale.inputs[0])
        control['earthstudio_parameter_paths'] = json.dumps(paths)
        for obj in list(scene.objects):
            if obj.get('earthstudio_layered_atmosphere'):
                bpy.data.objects.remove(obj, do_unlink=True)
                continue
            if obj.name.startswith(('WGS84 Earth', '大气显示')):
                obj.hide_render, obj.hide_viewport = True, True
        obj = create(scene, master, output.parent/'assets', images, manifest['sun'], control, paths)
        scene['earthstudio_atmosphere_profile'] = 'layered-optical-display-v4-color'
        effects = next(c for c in scene.collection.children if c.name.startswith('03｜'))
        effects.objects.link(obj)
        scene.collection.objects.unlink(obj)
        scene.cycles.samples = 64
        scene.cycles.adaptive_min_samples = 16
        scene.cycles.use_denoising = False
        scene.frame_set(1)
    bpy.context.window.scene = initial
    for image in images.values():
        destination = output.parent/'assets'/Path(bpy.path.abspath(image.filepath)).name
        if not destination.is_file():
            raise FileNotFoundError(destination)
        image.filepath = '//assets/'+destination.name
    bpy.data.texts.new('大气V4 · 调整说明.txt').write('''蓝色大气、夜间气辉各有独立开关、浓度、厚度、色相、饱和度、亮度。\n
色相0度，其他参数1为默认；饱和度0变灰，亮度0变黑但保留遮光，完全移除请关闭开关或将浓度设0。\n
参数可直接输入，悬停按I插入关键帧。每个分镜独立。暖色气辉仍只在夜侧显现。\n
采用不透明解析相机射线合成，避免透明混合壳的随机颗粒。未使用体积云、云高或修改原始GeoColor。\n
这是美术化显示近似，不是参考作者算法复现或真实大气反演。开关全关仍显示同一份原始观测。\n
当前天气仍为2026-10-20 22:40 UTC单景。原分镜和源工程保留，未读取或覆盖其他窗口中的未保存修改。\n''')
    bpy.ops.wm.save_as_mainfile(filepath=str(output), relative_remap=False)
    print('LAYERED_ATMOSPHERE_READY', output, flush=True)


if __name__ == '__main__':
    main()
