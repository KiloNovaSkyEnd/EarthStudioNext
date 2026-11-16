"""Run inside Blender against the actual browser-exported camera recording."""
import json
import math
from pathlib import Path
import sys
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.camera import validate,basis
from ges_next.isolation import require_writable

args=sys.argv[sys.argv.index('--')+1:]
track=validate(json.loads(Path(args[0]).read_text(encoding='utf-8')))
scene=bpy.context.scene; camera=scene.camera
max_position=0; max_orientation=0; max_projection=0
for sample in track['samples']:
    time=1+sample['seconds']*track['fps']; whole=math.floor(time)
    scene.frame_set(whole,subframe=time-whole)
    max_position=max(max_position,(camera.location-Vector(sample['position'])/1e6).length*1e6)
    forward=-(camera.matrix_world.to_3x3()@Vector((0,0,1)))
    up=camera.matrix_world.to_3x3()@Vector((0,1,0))
    max_orientation=max(max_orientation,(forward-Vector(sample['direction'])).length,(up-Vector(sample['up'])).length)
    right,_,_=basis(sample['direction'],sample['up'])
    for horizontal,vertical in [(0,0),(.25,.2),(-.3,-.2)]:
        # Construct known NDC locations using Cesium's exported vertical frustum.
        distance=1.0; half=math.tan(sample['verticalFov']/2)
        point=Vector(sample['position'])/1e6+Vector(sample['direction'])*distance+Vector(right)*(2*horizontal*half*sample['aspect'])+Vector(sample['up'])*(2*vertical*half)
        projected=world_to_camera_view(scene,camera,point)
        max_projection=max(max_projection,abs(projected.x-(.5+horizontal)),abs(projected.y-(.5+vertical)))
assert max_position<5, max_position  # float animation channels at planetary distances
assert max_orientation<1e-4,max_orientation
assert max_projection<1e-5,max_projection
# Verify the imported main camera remains locally editable in Blender.
scene.frame_set(1); original=camera.location.copy(); edited=original.copy(); edited.x+=.001
camera.location=edited; camera.keyframe_insert('location',frame=1)
scene.frame_set(2);scene.frame_set(1)
assert abs(camera.location.x-edited.x)<1e-6
assert not camera.constraints
camera.location=original;camera.keyframe_insert('location',frame=1)
report={'samples_checked':len(track['samples']),'all_sample_times_checked':True,
        'max_position_error_m':max_position,'max_orientation_vector_error':max_orientation,
        'max_normalized_screen_error':max_projection,'camera_import_verified':True,
        'blender_keyframe_edit_verified':True,
        'reference_shot_cameras':len(bpy.data.collections['Cesium reference shots'].objects) if 'Cesium reference shots' in bpy.data.collections else 0,
        'weather_materials_import_verified':False,'visual_match_render_verified':False}
out=require_writable(args[1]); out.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
