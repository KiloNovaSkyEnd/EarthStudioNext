"""One source-sequence rate shared by every scene in an Earth Studio project."""
import math
import json
import bpy
from scripts.blender_support.weather_fps import apply_scene
from scripts.blender_support.editable_camera import curves


def settings(scene=None):
    return bpy.data.worlds.get(scene.get('earthstudio_project_clock','')) if scene else None


def configure(scene,fps=30,world=None):
    if world is None:
        world=bpy.data.worlds.new('Earth Studio｜项目播放设置');world.use_fake_user=True
        world['earthstudio_source_clock']=True
        world['source_fps']=float(fps)
        world.id_properties_ui('source_fps').update(min=1,max=120,description='项目帧率：每帧依次使用一张源图。应用到整个项目。')
    scene['earthstudio_project_clock']=world.name
    return world


def owners(scene):
    yield scene
    for obj in scene.objects:
        yield obj
        if obj.type=='CAMERA':yield obj.data
        for slot in obj.material_slots:
            if slot.material and slot.material.node_tree:yield slot.material.node_tree


def apply_clock(scene):
    """Unbounded linear source clock: appending material never retimes its curve."""
    from scripts.blender_support.weather_fps import apply
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    start=scene['earthstudio_weather_start'];interval=scene['earthstudio_weather_interval']
    apply(control,path,start,start+interval/3600,interval,scene['earthstudio_weather_fps'],
          scene.render.fps/scene.render.fps_base,scene.frame_start)
    next(c for c in curves(control) if c.data_path==path).extrapolation='LINEAR'


def apply_project(scene=None):
    world=settings(scene or bpy.context.scene);fps=float(world['source_fps']) if world else 0
    if not math.isfinite(fps) or not 1<=fps<=120:raise ValueError('Project fps must be 1–120')
    scenes=[s for s in bpy.data.scenes if s.get('earthstudio_project_clock')==world.name]
    # Reject incompatible previously edited rates before changing anything.
    old_rates={round(s.render.fps/s.render.fps_base,6) for s in scenes}
    if len(old_rates)!=1:raise ValueError('Project scenes have different render rates; unify them before applying project fps')
    scale=fps/next(iter(old_rates));visited=set()
    strips=[(strip,strip.frame_final_start,strip.frame_final_end,strip.animation_offset_start,strip.animation_offset_end)
            for scene in scenes if scene.sequence_editor for strip in scene.sequence_editor.strips]
    for scene in scenes:
        old_start=scene.frame_start
        for owner in owners(scene):
            if not getattr(owner,'animation_data',None) or not owner.animation_data.action:continue
            for curve in curves(owner):
                if curve.as_pointer() in visited:continue
                visited.add(curve.as_pointer())
                for key in curve.keyframe_points:
                    for point in (key.co,key.handle_left,key.handle_right):point.x=1+(point.x-1)*scale
                curve.update()
        for marker in scene.timeline_markers:marker.frame=round(1+(marker.frame-1)*scale)
        scene.frame_start=round(1+(old_start-1)*scale)
        scene.frame_end=max(scene.frame_start,round(1+(scene.frame_end-1)*scale))
        scene.render.fps=round(fps);scene.render.fps_base=round(fps)/fps
        if 'earthstudio_weather_fps' in scene and scene.get('earthstudio_weather_clock_mode','sequence')!='mapped':
            scene['earthstudio_weather_fps']=fps;apply_clock(scene)
    # Source-scene duration changes can automatically resize Scene strips.
    # Restore final strip boundaries only after every referenced scene is updated.
    for strip,start,end,offset_start,offset_end in strips:
        strip.animation_offset_start=round(offset_start*scale);strip.animation_offset_end=round(offset_end*scale)
        strip.frame_final_start=round(1+(start-1)*scale);strip.frame_final_end=round(1+(end-1)*scale)
    return fps,len(scenes)
