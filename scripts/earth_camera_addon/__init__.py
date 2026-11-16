bl_info={'name':'Satellite Earth Camera','author':'Earth Studio','version':(0,3,0),
         'blender':(4,2,0),'location':'3D View > N > Satellite Earth','category':'3D View'}
import json
from pathlib import Path
import subprocess
import sys
import bpy

_process=None
_log=None
_request=None


def support(scene):
    folder=Path(scene['earth_blender_scripts'])
    if str(folder) not in sys.path: sys.path.insert(0,str(folder))


def poll():
    global _process,_log
    if _process is None: return None
    status=_request.with_suffix('.status.json')
    if status.is_file():
        try:
            record=json.loads(status.read_text(encoding='utf-8'))
            bpy.context.scene.earth_native_status=f"{record.get('stage')} {record.get('node','')}/{record.get('total','')}"
        except (ValueError,OSError): pass
    code=_process.poll()
    if code is None: return 2.0
    _log.close(); _log=None; _process=None
    result=_request.with_suffix('.result.json')
    if code==0 and result.is_file():
        try:
            support(bpy.context.scene)
            from blender_support.import_tiles import load
            load(result)
            bpy.context.scene.earth_native_status='原始细节已载入；Ctrl+S保存后可直接渲染'
        except Exception as error: bpy.context.scene.earth_native_status='载入失败: '+str(error)
    else: bpy.context.scene.earth_native_status='处理失败；查看请求目录的 .log 和 .status.json'
    return None


class EARTH_OT_prepare(bpy.types.Operator):
    bl_idname='earth.prepare_native'; bl_label='准备当前时间点的相机原始细节'
    def execute(self,context):
        global _process,_log,_request
        if _process is not None:
            self.report({'WARNING'},'已有原始细节任务运行'); return {'CANCELLED'}
        try:
            scene=context.scene; support(scene)
            if scene.get('earth_native_only',False):
                self.report({'INFO'},'此场景使用完整原生分块，无需准备低分辨率相机层级')
                return {'FINISHED'}
            from blender_support.camera_request import write
            _request=write(scene,scene.earth_native_all_nodes)
            engine=json.loads(scene['earth_engine_command'])
            _log=_request.with_suffix('.log').open('w',encoding='utf-8')
            _process=subprocess.Popen([*engine,'camera-tiles','--root',scene['earth_project_root'],'--request',str(_request)],
                stdout=_log,stderr=subprocess.STDOUT,cwd=scene['earth_engine_cwd'],
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            scene.earth_native_status='正在从原始卫星数据准备…'
            bpy.app.timers.register(poll,first_interval=2)
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'},str(error)); return {'CANCELLED'}


class EARTH_OT_free_camera(bpy.types.Operator):
    bl_idname='earth.free_camera'; bl_label='从当前视角新建自由相机'
    def execute(self,context):
        previous=context.scene.camera
        if previous is None: return {'CANCELLED'}
        evaluated=previous.evaluated_get(context.evaluated_depsgraph_get())
        camera=bpy.data.objects.new('Your camera · freely keyframe location and rotation',previous.data.copy())
        context.scene.collection.objects.link(camera); camera.matrix_world=evaluated.matrix_world.copy()
        context.scene.camera=camera
        for obj in context.selected_objects: obj.select_set(False)
        camera.select_set(True); context.view_layer.objects.active=camera
        if context.space_data.type=='VIEW_3D': context.space_data.region_3d.view_perspective='CAMERA'
        return {'FINISHED'}


class EARTH_PT_camera(bpy.types.Panel):
    bl_label='Satellite Earth'; bl_idname='EARTH_PT_camera'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='Satellite Earth'
    def draw(self,context):
        layout=self.layout; scene=context.scene
        if 'earth_project_root' not in scene:
            layout.label(text='请打开 Earth Studio 生成的场景'); return
        nodes=json.loads(scene['weather_utc_nodes']); hold=int(scene['weather_hold_frames'])
        index=min(len(nodes)-1,max(0,(scene.frame_current-1)//hold))
        layout.label(text='UTC '+nodes[index]); layout.label(text='灰色：缺测或排除的极区')
        layout.operator('earth.free_camera')
        if scene.get('earth_native_only',False):
            layout.label(text='原生分块地球；无低清底图')
            layout.label(text='可自由修改相机；不需要按机位降级重算')
            return
        layout.prop(scene,'earth_force_finest',text='强制最高原始细节（通常无需开启）')
        layout.prop(scene,'earth_native_all_nodes',text='为全部天气节点准备（用各节点相机）')
        layout.operator('earth.prepare_native'); layout.label(text=scene.earth_native_status)
        layout.label(text='原始细节准备后保存 .blend，再最终渲染')
        layout.label(text='移动镜头至新区域后重新准备；后台保留缓存')


classes=(EARTH_OT_prepare,EARTH_OT_free_camera,EARTH_PT_camera)
def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.earth_native_all_nodes=bpy.props.BoolProperty(default=False)
    bpy.types.Scene.earth_force_finest=bpy.props.BoolProperty(default=False)
    bpy.types.Scene.earth_native_status=bpy.props.StringProperty(default='可自由移动相机；最终渲染前准备原始细节')
def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    del bpy.types.Scene.earth_native_all_nodes; del bpy.types.Scene.earth_native_status; del bpy.types.Scene.earth_force_finest
