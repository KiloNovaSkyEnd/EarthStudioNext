"""Native editable VSE scene strips, without baking camera or weather animation."""
import bpy
from ges_next.layered_sequence.edit_list import layout

NAME='00｜连续成片'

def create(clips=None,name=NAME):
    selected={c['scene'] for c in clips} if clips else None
    shots=[s for s in bpy.data.scenes if s.get('layered_weather_sequence') and (selected is None or s.name in selected)]
    if not shots:raise ValueError('没有可用分镜')
    fps={(s.render.fps,s.render.fps_base,s.render.resolution_x,s.render.resolution_y) for s in shots}
    if len(fps)!=1:raise ValueError('合成前请统一分镜帧率和输出尺寸，不自动修改原场景')
    bounds={s.name:(s.frame_start,min(s.frame_end,s.frame_start+round(s['earthstudio_shot_duration_seconds']*s.render.fps/s.render.fps_base)-1)
        if 'earthstudio_shot_duration_seconds' in s else s.frame_end) for s in shots}
    plan=layout(clips or [dict(scene=s.name) for s in shots],bounds)
    if name in bpy.data.scenes:raise ValueError('现有连续成片场景保留；请在Blender继续编辑或选择新工程')
    scene=bpy.data.scenes.new(name);template=shots[0]
    if template.get('earthstudio_project_clock'):scene['earthstudio_project_clock']=template['earthstudio_project_clock']
    scene.render.fps=template.render.fps;scene.render.fps_base=template.render.fps_base
    scene.render.resolution_x=template.render.resolution_x;scene.render.resolution_y=template.render.resolution_y
    scene.render.resolution_percentage=template.render.resolution_percentage
    scene.render.engine=template.render.engine;scene.render.use_sequencer=True
    scene.view_settings.view_transform=template.view_settings.view_transform
    scene.view_settings.look=template.view_settings.look;scene.view_settings.exposure=template.view_settings.exposure;scene.view_settings.gamma=template.view_settings.gamma
    scene.display_settings.display_device=template.display_settings.display_device
    scene.sequencer_colorspace_settings.name=template.sequencer_colorspace_settings.name
    scene.sequence_editor_create();strips=scene.sequence_editor.strips
    for i,clip in enumerate(plan):
        source=bpy.data.scenes[clip['scene']]
        strip=strips.new_scene(f'{i+1:02} · {source.name}',source,channel=1,frame_start=clip['start'])
        strip.scene_input='CAMERA';strip.animation_offset_start=clip['source_in']-source.frame_start
        strip.animation_offset_end=source.frame_end-clip['source_out']
        strip.frame_final_start=clip['start'];strip.frame_final_end=clip['end']+1
        if int(strip.frame_final_start)!=clip['start'] or int(strip.frame_final_end)!=clip['end']+1:raise ValueError('分镜时间边界验证失败')
        scene.timeline_markers.new(strip.name,frame=clip['start'])
    scene.frame_start=1;scene.frame_end=plan[-1]['end'];scene['earthstudio_montage']=True
    scene.render.filepath='//renders/continuous/frame_'
    return scene,plan
