"""Run in a fresh Blender process after importing the JS-generated rate bundle."""
import bpy,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.weather_fps import apply_scene
from scripts.blender_support.editable_camera import curves
from datetime import datetime
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/blender_preview_modes.py'))
root=Path(__file__).resolve().parents[1]/'reports/weather_fps'
bundle=json.loads((root/'bundle.json').read_text())
proof=[]
for i,track in enumerate(bundle['tracks'],1):
    scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_'+str(i))
    bpy.context.window.scene=scene
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    maximum=0
    for sample in track['samples'][::13]+track['samples'][-1:]:
        frame=1+sample['seconds']*30;scene.frame_set(math.floor(frame),subframe=frame%1)
        expected=(datetime.fromisoformat(sample['timelineUtc'].replace('Z','+00:00'))-datetime.fromisoformat('2026-10-20T13:00:00+00:00')).total_seconds()/3600
        maximum=max(maximum,abs(control.path_resolve(path)-expected))
    assert maximum<1e-6,(scene.name,maximum)
    if i==1:
        original_end=scene.frame_end
        other=[(c.data_path,[(tuple(k.co),k.interpolation) for k in c.keyframe_points]) for c in curves(control) if c.data_path!=path]
        scene['earthstudio_weather_fps']=.25
        assert bpy.ops.earthstudio.apply_weather_fps()=={'FINISHED'}
        assert abs(apply_scene(scene)-8)<1e-8
        assert scene.frame_end==original_end
        assert other==[(c.data_path,[(tuple(k.co),k.interpolation) for k in c.keyframe_points]) for c in curves(control) if c.data_path!=path]
        scene.frame_set(61);assert abs(control.path_resolve(path)-1/12)<1e-6
    proof.append(dict(scene=scene.name,max_error_hours=maximum))
(root/'proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
print('OBSERVATION_FPS_PARITY_AND_BLENDER_EDIT_PASSED',flush=True)
