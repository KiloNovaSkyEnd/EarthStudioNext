"""Verify persisted project rate and source stepping with auto-execution disabled."""
import bpy,json
from pathlib import Path
rows=[]
for scene in bpy.data.scenes:
    if not scene.get('earthstudio_scene_track','').startswith('WEB_'):continue
    bpy.context.window.scene=scene
    world=bpy.data.worlds[scene['earthstudio_project_clock']]
    assert world['source_fps']==30 and scene.render.fps==30
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    for frame in [1,2,3]:
        scene.frame_set(frame);assert abs(control.path_resolve(path)-(frame-1)/6)<1e-6
    rows.append(scene.name)
assert len(rows)==3
Path(bpy.data.filepath).with_suffix('.reopen.json').write_text(json.dumps(dict(fps=30,source_step_per_frame=True,no_autoexec=True,scenes=rows),ensure_ascii=False,indent=2),encoding='utf-8')
print('PROJECT_CLOCK_FRESH_REOPEN_PASSED',flush=True)
