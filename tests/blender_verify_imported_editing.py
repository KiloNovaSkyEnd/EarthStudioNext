"""Exercise native I-key insertion and retiming on imported, independent takes."""
import bpy,json,math,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.editable_camera import curves

def matrix_error(a,b):return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))
report=[]
for scene in [s for s in bpy.data.scenes if str(s.get('earthstudio_scene_track','')).startswith('WEB_')]:
    bpy.context.window.scene=scene
    camera=scene.camera;control=bpy.data.objects[camera['earthstudio_controller']]
    paths=json.loads(control['earthstudio_parameter_paths'])
    original=control.animation_data.action
    control.animation_data.action=original.copy();control.animation_data.action_slot=control.animation_data.action.slots[0]
    scene.frame_set(1);before=camera.matrix_world.copy()
    others={s.name:s.camera.matrix_world.copy() for s in bpy.data.scenes if s!=scene}
    for key,change in [('rangeKm',500),('roll',15),('heading',20)]:
        owner,attr=paths['["'+key+'"]'].rsplit('.',1)
        setattr(control.path_resolve(owner),attr,control.path_resolve(paths['["'+key+'"]'])+change)
    scene.view_layers[0].objects.active=control
    for obj in scene.objects:obj.select_set(obj==control)
    area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
    region=next(r for r in area.regions if r.type=='WINDOW')
    with bpy.context.temp_override(area=area,region=region):assert bpy.ops.anim.keyframe_insert()=={'FINISHED'}
    scene.frame_set(2);scene.frame_set(1)
    assert (camera.matrix_world.translation-before.translation).length>.4
    assert all(matrix_error(pose,bpy.data.scenes[name].camera.matrix_world)<1e-8 for name,pose in others.items())
    control.animation_data.action=original;control.animation_data.action_slot=original.slots[0]
    reference=[]
    for fraction in [0,.2,.5,.8,1]:
        frame=1+fraction*(scene.frame_end-1);scene.frame_set(math.floor(frame),subframe=frame%1)
        reference.append((frame,camera.matrix_world.copy(),control.path_resolve(paths['["weatherHours"]'])))
    control.animation_data.action=original.copy();control.animation_data.action_slot=control.animation_data.action.slots[0]
    for curve in curves(control):
        for point in curve.keyframe_points:
            x,l,r=point.co.x,point.handle_left.x,point.handle_right.x
            point.co.x=1+(x-1)*2;point.handle_left.x=1+(l-1)*2;point.handle_right.x=1+(r-1)*2
    for frame,pose,hours in reference:
        frame=1+(frame-1)*2;scene.frame_set(math.floor(frame),subframe=frame%1)
        assert matrix_error(pose,camera.matrix_world)<1e-5
        assert abs(control.path_resolve(paths['["weatherHours"]'])-hours)<1e-5
    control.animation_data.action=original;control.animation_data.action_slot=original.slots[0];scene.frame_set(1)
    report.append(dict(scene=scene.name,native_seven_channel_keying=True,multi_parameter_edit=True,other_scenes_unchanged=True,retime_2x_preserves_path_and_weather=True))
assert len(report)==2
Path(sys.argv[sys.argv.index('--')+1]).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('IMPORTED_TAKES_NATIVE_EDIT_AND_RETIME_VERIFIED',flush=True)
