"""Plan a real UTC/camera request without fabricating missing weather images."""
import json
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_support.camera import create
from blender_support.camera_request import write

root=Path(sys.argv[sys.argv.index('--')+1]).resolve()
plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
bpy.ops.wm.read_factory_settings(use_empty=True); scene=bpy.context.scene
scene.frame_start=1; scene.frame_end=292
scene.render.resolution_x=1920; scene.render.resolution_y=1080; scene.render.resolution_percentage=100
scene['earth_project_root']=str(root); scene['weather_utc_nodes']=json.dumps(plan['frames']); scene['weather_hold_frames']=4
create(scene,full=True); request=write(scene,all_nodes=True)
nodes=json.loads(request.read_text(encoding='utf-8'))['nodes']
record={'request':str(request),'camera_frames_checked':292,'nodes':len(nodes),
        'cells':sum(len(n['cells']) for n in nodes),'finest_nodes':sum(any(c[2]==0 for c in n['cells']) for n in nodes),
        'limits':'Geometric footprint plan only; does not claim weather processed or rendered'}
(root/'reports/sequence_camera_request.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=False),flush=True)
