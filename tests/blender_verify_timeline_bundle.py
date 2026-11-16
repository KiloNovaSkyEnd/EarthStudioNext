"""Validate all camera tracks from the browser-authored keyframe bundle."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable

args=sys.argv[sys.argv.index('--')+1:]
bundle=json.loads(Path(args[0]).read_text(encoding='utf-8'))
scene=bpy.context.scene
cameras=[o for o in scene.objects if 'earthstudio_take_name' in o]
assert len(cameras)==len(bundle['tracks'])>=2
assert len({o.animation_data.action.as_pointer() for o in cameras})==len(cameras)
assert len({o.data.animation_data.action.as_pointer() for o in cameras})==len(cameras)
assert len({o['earthstudio_weather_interval'] for o in cameras})==1
errors={};count=0
for track in bundle['tracks']:
    camera=next(o for o in cameras if o['earthstudio_take_name']==track['name'])
    max_position=max_direction=0
    for sample in track['samples']:
        frame=1+sample['seconds']*track['fps'];integer=math.floor(frame)
        scene.frame_set(integer,subframe=frame-integer)
        max_position=max(max_position,(camera.location-Vector(sample['position'])/1e6).length*1e6)
        direction=-(camera.matrix_world.to_3x3()@Vector((0,0,1)))
        max_direction=max(max_direction,(direction-Vector(sample['direction'])).length)
        count+=1
    assert max_position<5 and max_direction<1e-4
    errors[track['name']]={'max_position_error_m':max_position,'max_direction_error':max_direction}
scene.frame_set(1)
others=[o.location.copy() for o in cameras[1:]];own=cameras[0].location.copy()
cameras[0].location.x+=.01;cameras[0].keyframe_insert('location',frame=1)
scene.frame_set(2);scene.frame_set(1)
assert all((o.location-before).length<1e-10 for o,before in zip(cameras[1:],others))
assert abs(cameras[0].location.x-own.x-.01)<1e-6
report={'camera_tracks':len(cameras),'samples_verified':count,'separate_editable_actions':True,'editing_one_does_not_change_other':True,'shared_weather_interval':True,'errors':errors,'weather_materials_imported':False}
require_writable(args[1]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
