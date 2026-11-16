"""All source camera samples, isolated edits, retiming and solar node curves."""
import sys,json,math
from pathlib import Path
import bpy
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.editable_camera import curves
from ges_next.camera import horizontal_lens_mm
bundle=json.loads(bpy.data.texts['camera_bundle.json'].as_string())
manifest=json.loads(bpy.data.texts['sequence_manifest.json'].as_string())
scenes={s['earthstudio_scene_track']:s for s in bpy.data.scenes}
report=[]
for track in bundle['tracks']:
    scene=scenes[track['keyframeTrack']['id']];bpy.context.window.scene=scene
    camera=scene.camera;control=bpy.data.objects[camera['earthstudio_controller']]
    paths=json.loads(control['earthstudio_parameter_paths'])
    maximum=dict(position_metres=0,direction=0,up=0,lens=0)
    for sample in track['samples']:
        f=1+sample['seconds']*track['fps'];scene.frame_set(math.floor(f),subframe=f%1)
        matrix=camera.matrix_world
        maximum['position_metres']=max(maximum['position_metres'],(matrix.translation-Vector(sample['position'])/1e6).length*1e6)
        maximum['direction']=max(maximum['direction'],(-(matrix.to_3x3()@Vector((0,0,1)))-Vector(sample['direction'])).length)
        maximum['up']=max(maximum['up'],((matrix.to_3x3()@Vector((0,1,0)))-Vector(sample['up'])).length)
        maximum['lens']=max(maximum['lens'],abs(camera.data.lens-horizontal_lens_mm(sample)))
    assert maximum['position_metres']<20 and maximum['direction']<3e-6 and maximum['up']<3e-6 and maximum['lens']<.0002,maximum
    shell=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
    sun_curves=[n for n in shell.data.materials[0].node_tree.nodes if n.bl_idname=='ShaderNodeFloatCurve']
    solar_max_error=0
    for axis,node in enumerate(sun_curves):
        for index,sun in enumerate(manifest['suns']):
            actual=node.mapping.evaluate(node.mapping.curves[0],index/72)
            solar_max_error=max(solar_max_error,abs(actual-sun[axis]))
            # Blender native FloatCurve is a sampled LUT; this is display-only
            # solar gating, independent of the unchanged scientific imagery.
            assert abs(actual-sun[axis])<.001,(node.label,index,actual,sun[axis])
    original=control.animation_data.action;control.animation_data.action=original.copy();control.animation_data.action_slot=control.animation_data.action.slots[0]
    scene.frame_set(1);before=camera.matrix_world.translation.copy()
    others={s.name:s.camera.matrix_world.copy() for s in bpy.data.scenes if s!=scene}
    path=paths['["rangeKm"]'];owner,attr=path.rsplit('.',1)
    setattr(control.path_resolve(owner),attr,control.path_resolve(path)+1500);control.keyframe_insert(path,frame=1)
    scene.frame_set(2);scene.frame_set(1)
    assert (camera.matrix_world.translation-before).length>1.4
    assert all(max(abs(matrix[r][c]-bpy.data.scenes[name].camera.matrix_world[r][c]) for r in range(4) for c in range(4))<1e-8 for name,matrix in others.items())
    control.animation_data.action=original;control.animation_data.action_slot=original.slots[0]
    references=[]
    for fraction in [0,.25,.5,.75,1]:
        frame=1+fraction*(scene.frame_end-1)
        scene.frame_set(math.floor(frame),subframe=frame%1)
        references.append((frame,camera.matrix_world.copy(),control.path_resolve(paths['["weatherHours"]'])))
    control.animation_data.action=original.copy();control.animation_data.action_slot=control.animation_data.action.slots[0]
    for curve in curves(control):
        for point in curve.keyframe_points:
            co,left,right=point.co.x,point.handle_left.x,point.handle_right.x
            point.co.x=1+(co-1)*2;point.handle_left.x=1+(left-1)*2;point.handle_right.x=1+(right-1)*2
    for frame,pose,hours in references:
        frame=1+(frame-1)*2;scene.frame_set(math.floor(frame),subframe=frame%1)
        assert max(abs(pose[r][c]-camera.matrix_world[r][c]) for r in range(4) for c in range(4))<1e-5
        assert abs(control.path_resolve(paths['["weatherHours"]'])-hours)<1e-5
    control.animation_data.action=original;control.animation_data.action_slot=original.slots[0]
    scene.frame_set(1)
    report.append(dict(scene=scene.name,samples=len(track['samples']),maximum=maximum,isolated_edit=True,retime_2x_preserves_camera_and_weather=True,sun_nodes=73,solar_node_max_component_error=solar_max_error))
Path(sys.argv[sys.argv.index('--')+1]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('CAMERA_SUN_AND_EDIT_ISOLATION_VERIFIED',flush=True)
