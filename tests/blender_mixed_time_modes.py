"""Tiny existing assets only: compare every exported frame to native weather F-curves."""
import bpy,json,sys,math
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from scripts.blender_import_dynamic_cameras import import_bundle
from scripts.blender_support.project_clock import settings,apply_project
from scripts.blender_support.editable_camera import curves
out=root/'reports/m14_editing';source=out/'mixed_bundle.json';target=out/'mixed.blend'
import_bundle(source,target)
bundle=json.loads(source.read_text());rows=[]
scenes=[bpy.data.scenes[r['scene']] for r in json.loads(target.with_suffix('.import.json').read_text())['scenes']]
for scene,track in zip(scenes,bundle['tracks']):
    bpy.context.window.scene=scene
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    curve=next(c for c in curves(control) if c.data_path==path)
    origin=__import__('datetime').datetime.fromisoformat(bundle['timelineProject']['weather']['startUtc'].replace('Z','+00:00'))
    errors=[]
    for sample in track['samples']:
        stamp=__import__('datetime').datetime.fromisoformat(sample['timelineUtc'].replace('Z','+00:00'))
        expected=(stamp-origin).total_seconds()/3600
        # Project clock deliberately extrapolates beyond availability; texture clamps to last.
        actual=curve.evaluate(1+sample['seconds']*24)
        errors.append(abs(min(1/3,actual)-expected))
    assert max(errors)<1e-5,(scene.name,max(errors))
    for frame in [1,2,3]:
        scene.frame_set(frame)
        formal=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere') and not o.get('earthstudio_preview_proxy'))
        textures=[n for n in formal.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE' and n.image.source=='SEQUENCE']
        expected=min(3,max(1,math.floor(control.path_resolve(path)*6+1.00001)))
        assert textures and all(frame+n.image_user.frame_offset==expected for n in textures)
    rows.append(dict(scene=scene.name,mode=scene['earthstudio_weather_clock_mode'],samples=len(errors),max_hours_error=max(errors)))
montage=next(s for s in bpy.data.scenes if s.name.startswith('00｜连续成片 · 导入分镜'))
assert list(montage.sequence_editor.strips)[0].frame_final_duration==11
world=settings(scenes[1]);world['source_fps']=30;apply_project(scenes[1])
assert all(s.render.fps==30 for s in scenes)
# Custom hold remains a hold after changing project fps.
control=bpy.data.objects[scenes[2].camera['earthstudio_controller']];path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
curve=next(c for c in curves(control) if c.data_path==path)
assert abs(curve.evaluate(1)-curve.evaluate(200))<1e-7
bpy.ops.wm.save_as_mainfile(filepath=str(out/'mixed30.blend'))
(out/'blender_mapping.json').write_text(json.dumps(dict(passed=True,rows=rows,trim_frames=11,custom_mode_preserved_at_30fps=True),ensure_ascii=False,indent=2),encoding='utf-8')
print('MIXED_TIME_MODES_NATIVE_BLENDER_PASSED',flush=True)
