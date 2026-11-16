"""Explicitly launched GUI helper: sharp paused composition, lightweight playback.

No embedded auto-execution is required. Native material visibility drivers remain
usable without this helper; final render visibility is never changed here.
"""
import json
import ctypes
import bpy
import blf
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_last_mode_state={}
_syncing_mode=False

def mode_changed(scene,context):
    global _syncing_mode
    if _syncing_mode:return
    resolved=controller(scene)
    if not resolved:return
    _syncing_mode=True
    try:
        for other in bpy.data.scenes:
            target=controller(other)
            if other!=scene and target and target[0]==resolved[0]:
                other.earthstudio_preview_mode=scene.earthstudio_preview_mode
    finally:_syncing_mode=False


def available_commit():
    if __import__('sys').platform != 'win32':
        return float('inf')
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in
            ['total_phys', 'avail_phys', 'total_commit', 'avail_commit', 'total_virtual', 'avail_virtual', 'extended']]
    value = MemoryStatus()
    value.length = ctypes.sizeof(value)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return value.avail_commit
    return 0


def release_detail_buffers(scene):
    # Clear decoded sequence buffers at a mode transition, never during rendering.
    if bpy.app.is_job_running('RENDER'):
        return
    images = set()
    for obj in scene.objects:
        if obj.get('earthstudio_layered_atmosphere'):
            for material in obj.data.materials:
                for node in material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        images.add(node.image)
    for image in images:
        image.gl_free()
        image.buffers_free()


def controller(scene):
    from scripts.blender_support.preview_controls import resolve
    return resolve(scene)


def apply_mode(scene, playing):
    resolved = controller(scene)
    if not resolved:
        return None
    obj, path = resolved
    mode = scene.earthstudio_preview_mode
    state_key=(scene.as_pointer(),obj.as_pointer())
    previous=_last_mode_state.get(state_key)
    high = mode == 'DETAIL' or (mode == 'AUTO' and not playing)
    owner, attribute = path.rsplit('.', 1)
    socket = obj.path_resolve(owner)
    current = getattr(socket, attribute)
    # A user may use the native Geometry Nodes switch instead of this panel.
    # Honor that explicit choice instead of AUTO resetting it every 0.2s.
    if previous and previous[:2]==(mode,playing) and bool(current)!=previous[2]:
        mode='DETAIL' if current else 'FAST'
        scene.earthstudio_preview_mode=mode
        high=bool(current)
    if high and not current and not bpy.app.background and available_commit() < 3.5 * 1024**3:
        scene['earthstudio_preview_memory_warning'] = '内存余量不足：先保留视频，关闭其他大工程后再看11K'
        return False
    scene['earthstudio_preview_memory_warning'] = ''
    if current != high:
        # A shared switch changes every linked shot, so release all their stale
        # decoded buffers rather than retaining 18 separate 11K frame caches.
        for linked in bpy.data.scenes:
            other=controller(linked)
            if other and other[0]==obj:release_detail_buffers(linked)
        setattr(socket, attribute, high)
        obj.update_tag()
    _last_mode_state[state_key]=(mode,playing,bool(high))
    return high


def tick():
    for window in bpy.context.window_manager.windows:
        playing = window.screen.is_animation_playing
        apply_mode(window.scene, playing)
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'PROPERTIES'}:
                area.tag_redraw()
    return 0.2


def draw_label():
    resolved = controller(bpy.context.scene)
    if not resolved:
        return
    obj, path = resolved
    high = bool(obj.path_resolve(path))
    # ASCII fallback avoids relying on Blender's bundled font CJK coverage.
    label = ('DETAIL 11000 x 11000' if high else bpy.context.scene.get('earthstudio_preview_label','PLAYBACK PROXY 4096 x 2048'))
    blf.position(0, 24, 45, 0)
    blf.size(0, 16)
    blf.color(0, 0.65, 0.9, 1.0, 1.0)
    blf.draw(0, label + (' | FINAL: 11K JPEG' if bpy.context.scene.get('layered_weather_sequence') else ' | FINAL: 11K PNG'))
    if bpy.context.scene.get('earthstudio_preview_memory_warning'):
        blf.position(0, 24, 68, 0)
        blf.color(0, 1.0, 0.65, 0.2, 1.0)
        blf.draw(0, 'LOW MEMORY: close other large projects to restore 11K')


class EARTHSTUDIO_PT_preview(bpy.types.Panel):
    bl_label = '画质与播放 · 最终渲染11K'
    bl_idname = 'EARTHSTUDIO_PT_preview'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Earth Studio'

    @classmethod
    def poll(cls, context):
        return controller(context.scene) is not None

    def draw(self, context):
        self.layout.operator('earthstudio.open_montage',text='查看全部分镜的连续成片',icon='SEQUENCE')
        self.layout.prop(context.scene, 'earthstudio_preview_mode', text='模式')
        if context.scene.get('earthstudio_shared_look'):
            self.layout.operator('earthstudio.select_shared_look',text='全片大气 / 地面（所有镜头共用）')
        if context.scene.get('earthstudio_frame_map_file'):
            self.layout.label(text='逐帧UTC已锁定：在摄影棚改帧率后更新运镜')
        else:
            from scripts.blender_support.project_clock import settings
            clock=settings(context.scene)
            if clock:
                self.layout.prop(clock, '["source_fps"]', text='项目源图播放fps')
                self.layout.operator('earthstudio.apply_project_fps', text='应用到整个项目')
                self.layout.label(text='一帧一张源图；所有分镜统一帧率')
            elif 'earthstudio_weather_fps' in context.scene:
                self.layout.separator()
                self.layout.prop(context.scene, '["earthstudio_weather_fps"]', text='云图观测时次/秒')
                self.layout.operator('earthstudio.apply_weather_fps', text='应用云图帧率（相机时长不变）')
                self.layout.label(text='提前播完保持末帧；较短镜头只播一部分')
        self.layout.label(text='自动：暂停看11K，播放用轻量预览')
        self.layout.label(text='流畅预览会变软；最终渲染不受影响')
        self.layout.label(text='无脚本打开：在全片大气 / 地面中切换11K' if context.scene.get('earthstudio_shared_look') else '无脚本打开：在运镜参数手动切换11K')
        if context.scene.get('earthstudio_preview_memory_warning'):
            self.layout.label(text='内存不足：关闭其他大工程再试', icon='ERROR')


class EARTHSTUDIO_OT_apply_project_fps(bpy.types.Operator):
    bl_idname='earthstudio.apply_project_fps'
    bl_label='应用项目源图帧率'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            if context.scene.get('earthstudio_frame_map_file'):raise ValueError('逐帧UTC工程请在摄影棚改帧率后更新运镜，避免图片与相机错位')
            from scripts.blender_support.project_clock import apply_project
            fps,count=apply_project(context.scene)
            context.scene.frame_set(context.scene.frame_start)
            self.report({'INFO'},f'项目{fps:g}fps，已同步{count}个场景；源图逐帧播放')
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'},str(error));return {'CANCELLED'}


class EARTHSTUDIO_OT_apply_weather_fps(bpy.types.Operator):
    bl_idname='earthstudio.apply_weather_fps'
    bl_label='应用独立云图帧率'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            if context.scene.get('earthstudio_frame_map_file'):raise ValueError('逐帧UTC工程请在摄影棚调整天气后更新运镜')
            from scripts.blender_support.weather_fps import apply_scene
            seconds=apply_scene(context.scene)
            context.scene.frame_set(context.scene.frame_current)
            self.report({'INFO'},f'云图区间耗时{seconds:.3f}秒；相机和成片时长不变')
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'},str(error));return {'CANCELLED'}


class EARTHSTUDIO_OT_open_montage(bpy.types.Operator):
    bl_idname='earthstudio.open_montage'
    bl_label='打开连续成片时间线'
    def execute(self,context):
        scenes=[s for s in bpy.data.scenes if s.get('earthstudio_montage')]
        if not scenes:
            self.report({'INFO'},'尚未生成连续成片场景');return {'CANCELLED'}
        context.window.scene=scenes[-1]
        # Use Blender's native sequencer preview and strip editing, not an empty 3D scene.
        for area in context.window.screen.areas:
            if area.type=='VIEW_3D':area.type='SEQUENCE_EDITOR';area.spaces.active.view_type='PREVIEW'
            elif area.type=='DOPESHEET_EDITOR':area.type='SEQUENCE_EDITOR';area.spaces.active.view_type='SEQUENCER'
        return {'FINISHED'}


class EARTHSTUDIO_OT_select_shared_look(bpy.types.Operator):
    bl_idname='earthstudio.select_shared_look'
    bl_label='选择全片共享外观'
    def execute(self,context):
        obj=bpy.data.objects.get(context.scene.get('earthstudio_shared_look',''))
        if obj is None:return {'CANCELLED'}
        for item in context.scene.objects:item.select_set(item==obj)
        context.view_layer.objects.active=obj
        for area in context.screen.areas:
            if area.type=='PROPERTIES':area.spaces.active.context='MODIFIER'
        return {'FINISHED'}


def register():
    from scripts.blender_support.preview_controls import repair_all
    from scripts.blender_support.airglow_visibility import repair_all as repair_airglow
    repair_airglow()
    repair_all()
    if hasattr(bpy.types.Scene, 'earthstudio_preview_mode'):
        return
    bpy.types.Scene.earthstudio_preview_mode = bpy.props.EnumProperty(
        name='预览画质',
        items=[('AUTO', '自动：暂停清晰／播放流畅', ''),
               ('DETAIL', '11K细节（播放可能卡顿）', ''),
               ('FAST', '流畅预览（不影响最终渲染）', '')],
        default='AUTO',update=mode_changed)
    bpy.utils.register_class(EARTHSTUDIO_OT_apply_project_fps)
    bpy.utils.register_class(EARTHSTUDIO_OT_apply_weather_fps)
    bpy.utils.register_class(EARTHSTUDIO_OT_open_montage)
    bpy.utils.register_class(EARTHSTUDIO_OT_select_shared_look)
    bpy.utils.register_class(EARTHSTUDIO_PT_preview)
    if not bpy.app.background:
        @bpy.app.handlers.persistent
        def on_load(_):
            _last_mode_state.clear()
            repair_airglow()
            repair_all()
        bpy.app.handlers.load_post.append(on_load)
        bpy.types.SpaceView3D.draw_handler_add(draw_label, (), 'WINDOW', 'POST_PIXEL')
        bpy.app.timers.register(tick, first_interval=0.2, persistent=True)


register()
