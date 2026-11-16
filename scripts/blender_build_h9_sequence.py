"""Upgrade saved V4 into independent native-weather animated camera scenes."""
import json,sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from scripts.blender_support.layered_atmosphere import create
from scripts.blender_support.editable_camera import curves

out=require_writable(sys.argv[sys.argv.index('--')+1])
target=out/'Earth_Studio_12小时动态天气.blend'
if target.exists():raise FileExistsError('Existing delivery preserved')
manifest=json.loads((out/'sequence_manifest.json').read_text())
master=json.loads((out/'native_master.json').read_text())
for obj in list(bpy.data.objects):
    if obj.get('earthstudio_layered_atmosphere') or obj.name.startswith(('WGS84 Earth','大气显示')):
        bpy.data.objects.remove(obj,do_unlink=True)
for image in list(bpy.data.images):
    if image.source=='FILE':bpy.data.images.remove(image,do_unlink=True)
images={}
for tile in master['tiles']:
    path=out/'assets'/Path(tile['path']).stem/'weather_0001.tif'
    image=bpy.data.images.load(str(path),check_existing=False)
    image.name=Path(tile['path']).stem+' · 73时次序列'
    image.colorspace_settings.name='sRGB';image.alpha_mode='STRAIGHT'
    images[tile['path']]=image
for scene in bpy.data.scenes:
    bpy.context.window.scene=scene
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    paths=json.loads(control['earthstudio_parameter_paths'])
    modifier=control.modifiers[0];group=modifier.node_group
    socket=group.interface.new_socket(name='天气时间（小时 UTC−7）',in_out='INPUT',socket_type='NodeSocketFloat')
    socket.min_value,socket.max_value,socket.default_value=6,18,6
    socket.description='6至18点；小数小时。6.5=06:30。与相机动画独立，可输入、插帧、改速度。07:40缺档显示灰色。'
    path=f'modifiers["{modifier.name}"].properties.inputs.{socket.identifier}.value'
    paths['["weatherHours"]']=path
    control['earthstudio_parameter_paths']=json.dumps(paths)
    # Participate in hidden geometry to keep the native modifier input enabled.
    node_in=next(n for n in group.nodes if n.bl_idname=='NodeGroupInput')
    scale=next(n for n in group.nodes if n.bl_idname=='ShaderNodeMath' and n.operation=='MULTIPLY' and abs(n.inputs[1].default_value-1e-8)<1e-12)
    previous=scale.inputs[0].links[0].from_socket
    add=group.nodes.new('ShaderNodeMath');add.operation='ADD'
    group.links.new(previous,add.inputs[0]);group.links.new(node_in.outputs[socket.name],add.inputs[1]);group.links.new(add.outputs[0],scale.inputs[0])
    value=getattr(modifier.properties.inputs,socket.identifier)
    for frame,hour in [(scene.frame_start,6),(scene.frame_end,18)]:
        value.value=float(hour);control.keyframe_insert(data_path=path,frame=frame)
    for curve in curves(control):
        if curve.data_path==path:
            for key in curve.keyframe_points:key.interpolation='LINEAR'
    shell=create(scene,master,out/'assets',images,dict(vectors=manifest['suns']),control,paths)
    effects=next(c for c in scene.collection.children if c.name.startswith('03｜'))
    effects.objects.link(shell);scene.collection.objects.unlink(shell)
    for node in shell.data.materials[0].node_tree.nodes:
        if node.bl_idname!='ShaderNodeTexImage':continue
        user=node.image_user;user.frame_start=1;user.frame_duration=1000000;user.use_auto_refresh=True
        driver=user.driver_add('frame_offset').driver
        var=driver.variables.new();var.name='hours';var.targets[0].id=control;var.targets[0].data_path=path
        driver.expression='min(73,max(1,floor((hours-6)*6+1.00001)))-min(1000000,max(0,frame))'
    scene['weather_start_utc']='2026-10-20T13:00:00Z';scene['weather_end_utc']='2026-10-21T01:00:00Z'
    scene['weather_missing_utc']='2026-10-20T14:40:00Z';scene['weather_native_sequence']=True
    scene.render.resolution_x,scene.render.resolution_y=1920,1080
    scene.render.resolution_percentage=100
    scene.render.filepath='//renders/'+scene.name.replace('｜','_')+'/frame_'
    scene.cycles.samples=64;scene.cycles.adaptive_min_samples=16;scene.cycles.use_denoising=False
    for index in [0,10,12,24,36,48,60,72]:
        node=manifest['nodes'][index]
        label=('缺档 · ' if node['missing'] else '天气 · ')+f'{6+index//6:02}:{index%6*10:02} UTC−7'
        scene.timeline_markers.new(label,frame=round(scene.frame_start+index/72*(scene.frame_end-scene.frame_start)))
    scene.frame_set(1)
for image in images.values():
    image.source='SEQUENCE'
    image.filepath=bpy.path.relpath(image.filepath,start=str(out))
for text in list(bpy.data.texts):
    if any(s in text.name for s in ['三步操作','START_HERE','大气V4']):bpy.data.texts.remove(text)
bpy.data.texts.new('00｜动态天气 · 从这里开始.txt').write('''打开场景后先选右上方分镜，再选01｜运镜参数，右侧扳手面板可直接改中文参数。
播放/拖动时间轴：天气真实变化，相机按各自关键帧运动。首次换时刻需读取原生大图，实时播放可能掉帧；正式渲染逐帧读取。
天气时间（小时 UTC−7）独立于相机：6=06:00，6.5=06:30，18=18:00。改后悬停按I保存关键帧；可在曲线编辑器调整速度。
本文件每个分镜默认在自己的完整时长内播放同样12小时天气；不同场景可独立设计相同时间段的镜头。
2026-10-20 07:40 UTC−7缺少真实观测，该节点为灰色缺测，没有复制邻帧或生成补帧。
蓝色大气、夜间气辉分别开关；各自浓度/厚度/色相/饱和度/亮度均可输入和插帧。太阳随天气时钟变化。
相机控制包括目标经纬度、绕行、俯看、距离、画面旋转和透视；已有运镜曲线保留，可继续修改。
F12渲染当前帧，Ctrl+F12渲染本场景动画。渲染分辨率可在输出设置中修改，不限制原生素材细节。
整体保留assets文件夹；无需网页、L1、Python科学环境、插件或自动运行脚本。各素材为原生影像分块，未观测半球为灰色。
''')
text=bpy.data.texts.get('native_master.json')
if text:text.clear();text.write(json.dumps(master,ensure_ascii=False))
text=bpy.data.texts.get('package_manifest.json')
if text:text.clear();text.write(json.dumps(dict(schema=manifest['schema'],weatherAnimated=True,nativeShape=[22000,22000],nodes=manifest['nodes']),ensure_ascii=False))
bpy.data.texts.new('sequence_manifest.json').write(json.dumps(manifest,ensure_ascii=False))
bpy.context.window.scene=list(bpy.data.scenes)[2]
bpy.ops.wm.save_as_mainfile(filepath=str(target),relative_remap=False)
print('ANIMATED_NATIVE_DELIVERY_SAVED',target,flush=True)
