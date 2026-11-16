"""Actually record two poses using the native seven-channel keying operator."""
import bpy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.editable_camera import curves,PARAMETERS
scene=bpy.context.scene;assert scene['earthstudio_scene_track']=='USER'
control=bpy.data.objects[scene.camera['earthstudio_controller']]
paths=json.loads(control['earthstudio_parameter_paths'])
assert len(curves(control))==1 and curves(control)[0].data_path==paths['["weatherHours"]']
assert len(scene.keying_sets.active.paths)==7
others={s.name:s.camera.matrix_world.copy() for s in bpy.data.scenes if s!=scene}
def insert_pose():
    area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
    region=next(r for r in area.regions if r.type=='WINDOW')
    with bpy.context.temp_override(area=area,region=region):
        return bpy.ops.anim.keyframe_insert()
scene.frame_set(1);first=scene.camera.matrix_world.copy()
assert insert_pose()=={'FINISHED'}
assert len(curves(control))==8
scene.frame_set(901)
for key,val in dict(heading=45.,pitch=-90.,rangeKm=2800.,roll=20.,fov=45.).items():
    owner,attr=paths['["'+key+'"]'].rsplit('.',1);setattr(control.path_resolve(owner),attr,val)
control.update_tag();bpy.context.view_layer.update()
assert insert_pose()=={'FINISHED'}
scene.frame_set(1);assert max(abs(first[r][c]-scene.camera.matrix_world[r][c]) for r in range(4) for c in range(4))<1e-5
scene.frame_set(451);middle=scene.camera.matrix_world.copy()
assert (middle.translation-first.translation).length>.5
assert all(len(c.keyframe_points)==2 for c in curves(control))
assert abs(control.path_resolve(paths['["weatherHours"]'])-12)<1e-5
assert all(max(abs(matrix[r][c]-bpy.data.scenes[name].camera.matrix_world[r][c]) for r in range(4) for c in range(4))<1e-8 for name,matrix in others.items())
from scripts.blender_support.gpu import configure
configure(scene);scene.cycles.samples=4;scene.cycles.adaptive_min_samples=4
scene.render.resolution_x,scene.render.resolution_y=640,360;scene.render.resolution_percentage=100
renders=Path(sys.argv[sys.argv.index('--')+1]).parent/'user_take_frames';renders.mkdir(exist_ok=True)
for frame in [1,451,901]:
    scene.frame_set(frame);scene.render.filepath=str(renders/f'pose_{frame:04d}.png');bpy.ops.render.render(write_still=True)
Path(sys.argv[sys.argv.index('--')+1]).write_text(json.dumps(dict(clean_user_take=True,native_keying_operator_executed_twice=True,
    camera_channels=7,independent_weather_clock=True,interpolated_camera_motion=True,original_five_scenes_unchanged=True,
    actual_custom_keyframe_poses_rendered=[1,451,901]),indent=2),encoding='utf-8')
print('USER_TAKE_TWO_NATIVE_POSES_VERIFIED',flush=True)
