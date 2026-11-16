"""A clean sixth take with a native seven-parameter keying set; no addon."""
import bpy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.layered_atmosphere import create
from scripts.blender_support.editable_camera import PARAMETERS
target=Path(sys.argv[sys.argv.index('--')+1])
if target.exists():raise FileExistsError('Existing final scene preserved')
source=list(bpy.data.scenes)[2];bpy.context.window.scene=source;source.frame_set(1)
scene=source.copy();scene.name='06｜自己做运镜 · 30秒';scene.use_fake_user=True
for collection in list(scene.collection.children):scene.collection.children.unlink(collection)
objects={}
def clone_collection(old):
    new=bpy.data.collections.new('自由运镜 · '+old.name)
    for obj in old.objects:
        copy=obj.copy()
        if obj.type=='CAMERA':copy.data=obj.data.copy()
        new.objects.link(copy);objects[obj]=copy
    for child in old.children:new.children.link(clone_collection(child))
    return new
rig=next(c for c in source.collection.children if c.name.startswith('01｜'))
scene.collection.children.link(clone_collection(rig))
for old,new in objects.items():
    if old.parent in objects:new.parent=objects[old.parent]
    for owner in [new,new.data if new.type=='CAMERA' else None]:
        if owner and owner.animation_data:
            for curve in owner.animation_data.drivers:
                for var in curve.driver.variables:
                    for t in var.targets:
                        if t.id in objects:t.id=objects[t.id]
scene.camera=objects[source.camera];control=objects[bpy.data.objects[source.camera['earthstudio_controller']]]
control.name='01｜运镜参数 · 自己做运镜';control.animation_data_clear()
control['earthstudio_editable_track']='USER';scene['earthstudio_scene_track']='USER'
scene.camera['earthstudio_editable_camera']='USER';scene.camera['earthstudio_controller']=control.name
paths=json.loads(control['earthstudio_parameter_paths'])
def value(key,val):
    owner,attribute=paths['["'+key+'"]'].rsplit('.',1);setattr(control.path_resolve(owner),attribute,val)
for key,val in dict(targetLon=130.7,targetLat=18.,heading=0.,pitch=-45.,rangeKm=4500.,roll=0.,fov=40.).items():value(key,val)
scene.frame_start,scene.frame_end=1,901;scene.render.filepath='//renders/06_自己做运镜/frame_'
for frame,hour in [(1,6.),(901,18.)]:
    value('weatherHours',hour);control.keyframe_insert(paths['["weatherHours"]'],frame=frame)
from scripts.blender_support.editable_camera import curves
for curve in curves(control):
    for point in curve.keyframe_points:point.interpolation='LINEAR'
keyset=scene.keying_sets.new(idname='EarthStudioCameraSeven',name='记录当前运镜 · 七项参数')
for key in PARAMETERS:keyset.paths.add(control,paths['["'+key+'"]'])
scene.keying_sets.active_index=len(scene.keying_sets)-1
manifest=json.loads(bpy.data.texts['sequence_manifest.json'].as_string())
master=json.loads(bpy.data.texts['native_master.json'].as_string())
images={Path(bpy.path.abspath(i.filepath)).parent.name+'.tif':i for i in bpy.data.images if i.source=='SEQUENCE'}
for image in images.values():image.source='FILE';image.reload()
bpy.context.window.scene=scene
shell=create(scene,master,target.parent/'assets',images,dict(vectors=manifest['suns']),control,paths)
for image in images.values():image.source='SEQUENCE'
for node in shell.data.materials[0].node_tree.nodes:
    if node.bl_idname!='ShaderNodeTexImage':continue
    user=node.image_user;user.frame_start=1;user.frame_duration=1000000;user.use_auto_refresh=True
    d=user.driver_add('frame_offset').driver;v=d.variables.new();v.name='hours';v.targets[0].id=control;v.targets[0].data_path=paths['["weatherHours"]']
    d.expression='min(73,max(1,floor((hours-6)*6+1.00001)))-min(1000000,max(0,frame))'
for marker in list(scene.timeline_markers):scene.timeline_markers.remove(marker)
for frame,label in [(1,'起点 · 06:00 UTC−7'),(126,'缺档 · 07:40 UTC−7'),(451,'中点 · 12:00 UTC−7'),(901,'终点 · 18:00 UTC−7')]:scene.timeline_markers.new(label,frame=frame)
bpy.context.window.scene=scene;scene.frame_set(1)
for obj in scene.view_layers[0].objects:obj.select_set(obj==control)
scene.view_layers[0].objects.active=control
scene['earthstudio_user_take']='Camera starts with no keyframes; weather has independent 6→18 clock. Native seven-channel keying set active.'
guide=bpy.data.texts['00｜动态天气 · 从这里开始.txt']
guide.write('''\n默认打开06｜自己做运镜：相机没有预设动画。\n第1帧摆起点，鼠标放三维画面按I（已启用“记录当前运镜 · 七项参数”）；第451或901帧改数值后再按I。\n可在时间轴“键控集”下拉选该项；备用方法是各参数栏右键→插入关键帧。Ctrl+Z撤销、Ctrl+Shift+Z重做。\n七项为目标经纬度、绕目标角度、俯看角度、距离、画面旋转和垂直画角。天气时钟独立插帧。\n''')
bpy.ops.wm.save_as_mainfile(filepath=str(target),relative_remap=False)
print('USER_TAKE_NATIVE_KEYING_SET_READY',target,flush=True)
