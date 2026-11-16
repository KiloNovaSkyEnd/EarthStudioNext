"""Mixed orbit/free-pose import, multi-turn roll, edit/retime and actual renders."""
import bpy,json,sys,copy,math,importlib.util
from pathlib import Path
from mathutils import Quaternion,Vector
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from scripts.blender_support.editable_camera import curves
from scripts.blender_support.gpu import configure
from ges_next.camera import horizontal_lens_mm
spec=importlib.util.spec_from_file_location('dynamic_import',root/'scripts/blender_import_dynamic_cameras.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
out=root/'reports/h9_web_bridge/free_camera';out.mkdir(exist_ok=True)
bundle=json.loads((root/'reports/h9_web_bridge/actual_browser_bundle.json').read_text(encoding='utf-8'))
free=bundle['tracks'][1];free['name']='自由相机 · 多圈滚转验收'
for key in free['keyframeTrack']['keys']:key.pop('orbit',None)
for sample in free['samples']:
    fraction=sample['seconds']/free['samples'][-1]['seconds']
    sample['up']=list(Quaternion(Vector(sample['direction']),math.radians(765)*fraction)@Vector(sample['up']))
args=sys.argv[sys.argv.index('--')+1:]
actual_browser=len(args)>1
if actual_browser:
    bundle=json.loads(Path(args[1]).read_text(encoding='utf-8'));free=bundle['tracks'][-1]
source=out/'mixed_free_camera.json';source.write_text(json.dumps(bundle,ensure_ascii=False),encoding='utf-8')
target=Path(sys.argv[sys.argv.index('--')+1]);module.import_bundle(source,target)
scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_'+str(len(bundle['tracks'])));bpy.context.window.scene=scene
camera=scene.camera;control=bpy.data.objects[camera['earthstudio_controller']];paths=json.loads(control['earthstudio_parameter_paths'])
assert scene['earthstudio_camera_edit_mode']=='native_transform_lens_30fps' and camera.parent is None
assert len(curves(camera))==7 and len(curves(camera.data))==1 and len(curves(control))==1
assert all(p.id in (camera,camera.data) for p in scene.keying_sets.active.paths)
errors=dict(position_metres=0,direction=0,up=0,lens=0)
for sample in free['samples']:
    f=1+sample['seconds']*30;scene.frame_set(math.floor(f),subframe=f%1);matrix=camera.matrix_world
    errors['position_metres']=max(errors['position_metres'],(matrix.translation-Vector(sample['position'])/1e6).length*1e6)
    errors['direction']=max(errors['direction'],(-(matrix.to_3x3()@Vector((0,0,1)))-Vector(sample['direction'])).length)
    errors['up']=max(errors['up'],((matrix.to_3x3()@Vector((0,1,0)))-Vector(sample['up'])).length)
    errors['lens']=max(errors['lens'],abs(camera.data.lens-horizontal_lens_mm(sample)))
    assert abs(control.path_resolve(paths['["weatherHours"]'])-(6+sample['seconds']/40*12))<1e-4
assert errors['position_metres']<3 and max(errors['direction'],errors['up'])<2e-6 and errors['lens']<1e-4,errors
configure(scene);scene.cycles.samples=4;scene.cycles.adaptive_min_samples=4
scene.render.resolution_x,scene.render.resolution_y=640,360
for frame in [1,301,901]:
    scene.frame_set(frame);scene.render.filepath=str(out/f'free_{frame:04d}.png');bpy.ops.render.render(write_still=True)

# Native I-key records object transforms and camera-data focal length.
scene.frame_set(1);before=camera.matrix_world.copy();others={s.name:s.camera.matrix_world.copy() for s in bpy.data.scenes if s!=scene}
owners=(camera,camera.data,control);originals=[o.animation_data.action for o in owners]
for owner,action in zip(owners,originals):owner.animation_data.action=action.copy();owner.animation_data.action_slot=owner.animation_data.action.slots[0]
bpy.context.view_layer.update()
camera.location.x+=.5;camera.data.lens+=5
camera.update_tag();bpy.context.view_layer.update()
scene.view_layers[0].objects.active=camera
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
with bpy.context.temp_override(area=area,region=region):assert bpy.ops.anim.keyframe_insert()=={'FINISHED'}
scene.frame_set(2);scene.frame_set(1);assert (camera.matrix_world.translation-before.translation).length>.49
def delta(a,b):return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))
assert all(delta(m,bpy.data.scenes[n].camera.matrix_world)<1e-8 for n,m in others.items())
for owner,action in zip(owners,originals):owner.animation_data.action=action;owner.animation_data.action_slot=action.slots[0]
references=[]
for frame in [1,301,601,901,1201]:
    scene.frame_set(frame);references.append((frame,camera.matrix_world.copy(),camera.data.lens,control.path_resolve(paths['["weatherHours"]'])))
for owner,action in zip(owners,originals):
    owner.animation_data.action=action.copy();owner.animation_data.action_slot=owner.animation_data.action.slots[0]
    for curve in curves(owner):
        for point in curve.keyframe_points:
            x,l,r=point.co.x,point.handle_left.x,point.handle_right.x
            point.co.x=1+(x-1)*2;point.handle_left.x=1+(l-1)*2;point.handle_right.x=1+(r-1)*2
for frame,pose,lens,hours in references:
    scene.frame_set(1+(frame-1)*2);assert delta(pose,camera.matrix_world)<1e-5
    assert abs(lens-camera.data.lens)<1e-5 and abs(hours-control.path_resolve(paths['["weatherHours"]']))<1e-5
(out/('actual_browser_verification.json' if actual_browser else 'verification.json')).write_text(json.dumps(dict(source='Actual browser export of loaded free-pose test project' if actual_browser else 'Deterministic multi-turn free-pose fixture derived from actual browser samples; not a new UI gesture recording',samples=len(free['samples']),errors=errors,mixed_orbit_and_free_pose=not actual_browser,native_I_key_edit=True,isolated=True,retime_camera_lens_weather=True,rendered_frames=[1,301,901]),ensure_ascii=False,indent=2),encoding='utf-8')
print('FREE_CAMERA_IMPORT_EDIT_RETIME_RENDER_VERIFIED',flush=True)
