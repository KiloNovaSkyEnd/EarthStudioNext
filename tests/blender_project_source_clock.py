import bpy,json,sys,runpy,math
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from scripts.blender_support.project_clock import settings
from scripts.blender_support.editable_camera import curves
runpy.run_path(str(root/'scripts/blender_preview_modes.py'))
scenes=sorted([s for s in bpy.data.scenes if s.get('earthstudio_scene_track','').startswith('WEB_')],key=lambda s:s.name)
assert len(scenes)==3
world=settings(scenes[0]);assert world and world['source_fps']==24
records=[]
for scene in scenes:
    assert settings(scene)==world
    assert abs(scene.render.fps/scene.render.fps_base-24)<1e-5
    bpy.context.window.scene=scene
    control=bpy.data.objects[scene.camera['earthstudio_controller']];path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    for frame in [1,2,3]:
        scene.frame_set(frame);assert abs(control.path_resolve(path)-(frame-1)/6)<1e-6
        formal=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere') and not o.get('earthstudio_preview_proxy'))
        nodes=[n for n in formal.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE' and n.image.source=='SEQUENCE']
        assert nodes and all(frame+n.image_user.frame_offset==frame for n in nodes)
    records.append(dict(scene=scene.name,fps=24,source_frames=[0,1,2]))
montage=next(s for s in bpy.data.scenes if s.name.startswith('00｜连续成片 · 导入分镜'))
assert settings(montage)==world
original=[(s.name,s['earthstudio_shot_duration_seconds']) for s in scenes]
control=bpy.data.objects[scenes[0].camera['earthstudio_controller']];path=json.loads(control['earthstudio_parameter_paths'])['["heading"]']
curve=next(c for c in curves(control) if c.data_path==path)
before=[(k.co.x,k.co.y,tuple(k.handle_left),tuple(k.handle_right)) for k in curve.keyframe_points]
bpy.context.window.scene=scenes[0];world['source_fps']=30
assert bpy.ops.earthstudio.apply_project_fps()=={'FINISHED'}
assert original==[(s.name,s['earthstudio_shot_duration_seconds']) for s in scenes]
after=[(k.co.x,k.co.y,tuple(k.handle_left),tuple(k.handle_right)) for k in curve.keyframe_points]
for a,b in zip(before,after):
    assert abs((a[0]-1)/24-(b[0]-1)/30)<1e-6 and abs(a[1]-b[1])<1e-6
    for old,new in zip(a[2:],b[2:]):assert abs((old[0]-1)/24-(new[0]-1)/30)<1e-6 and abs(old[1]-new[1])<1e-5
for scene in scenes:
    bpy.context.window.scene=scene
    assert scene.render.fps==30
    c=bpy.data.objects[scene.camera['earthstudio_controller']];p=json.loads(c['earthstudio_parameter_paths'])['["weatherHours"]']
    scene.frame_set(2);assert abs(c.path_resolve(p)-1/6)<1e-6
assert montage.render.fps==30
strips=list(montage.sequence_editor.strips)
assert [(s.frame_final_start,s.frame_final_end) for s in strips]==[(1,301),(301,1051),(1051,1291)]
bpy.context.window.scene=scenes[0]
bpy.ops.wm.save_as_mainfile(filepath=str(root/'reports/project_source_clock/project30.blend'))
(root/'reports/project_source_clock/proof.json').write_text(json.dumps(dict(imported=records,changed_fps=30,total_seconds=43,camera_seconds_and_handles_preserved=True,source_per_project_frame=True),ensure_ascii=False,indent=2),encoding='utf-8')
print('PROJECT_SOURCE_FPS_BLENDER_IMPORT_AND_GLOBAL_EDIT_PASSED',flush=True)
