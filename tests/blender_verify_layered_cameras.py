"""Real exported camera samples plus independent layered-shader driver targets."""
import json,math,sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.camera import horizontal_lens_mm

args=sys.argv[sys.argv.index('--')+1:];bundle=json.loads(Path(args[0]).read_text(encoding='utf-8'));results=[]
for i,track in enumerate(bundle['tracks'],1):
    scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_'+str(i));bpy.context.window.scene=scene
    camera=scene.camera;control=bpy.data.objects[camera['earthstudio_controller']]
    errors=dict(position_metres=0,direction=0,up=0,lens=0)
    for sample in [track['samples'][j] for j in (0,len(track['samples'])//2,len(track['samples'])-1)]:
        frame=1+30*sample['seconds'];scene.frame_set(math.floor(frame),subframe=frame%1)
        matrix=camera.matrix_world
        errors['position_metres']=max(errors['position_metres'],(matrix.translation-Vector(sample['position'])/1e6).length*1e6)
        errors['direction']=max(errors['direction'],(-(matrix.to_3x3()@Vector((0,0,1)))-Vector(sample['direction'])).length)
        errors['up']=max(errors['up'],((matrix.to_3x3()@Vector((0,1,0)))-Vector(sample['up'])).length)
        errors['lens']=max(errors['lens'],abs(camera.data.lens-horizontal_lens_mm(sample)))
    assert errors['position_metres']<20 and errors['direction']<3e-6 and errors['up']<3e-6 and errors['lens']<.0002,errors
    for obj in scene.objects:
        if not obj.get('earthstudio_layered_atmosphere'):continue
        for curve in obj.data.materials[0].node_tree.animation_data.drivers:
            for variable in curve.driver.variables:
                if variable.name in ('v','hours'):assert variable.targets[0].id==control,'Cross-scene control reference'
    results.append(dict(scene=scene.name,maximum=errors,independent_shader_controls=True,edit_mode=scene['earthstudio_camera_edit_mode']))
Path(args[1]).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('LAYERED_CAMERAS_NUMERICALLY_VERIFIED',flush=True)
