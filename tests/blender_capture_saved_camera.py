import bpy,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_1')
bpy.context.window.scene=scene
rows=[]
for frame in range(scene.frame_start,scene.frame_end+1):
 scene.frame_set(frame)
 rows.append(dict(frame=frame,matrix=[list(row) for row in scene.camera.matrix_world]))
(root/'reports/h9_11k_optimization/original_saved_camera.json').write_text(json.dumps(rows),encoding='utf-8')
print('ORIGINAL_CAMERA_CAPTURED',len(rows),flush=True)
