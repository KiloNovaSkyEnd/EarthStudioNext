"""Fresh standalone Blender: relocated imported camera, assets, switches and I key."""
from pathlib import Path
import bpy,json,sys,math
from mathutils import Quaternion

out=Path(sys.argv[sys.argv.index('--')+1])
if not out.is_absolute():raise ValueError('Use an absolute report path; Blender may change the working directory')
out.mkdir(exist_ok=True,parents=True)
root=Path(bpy.data.filepath).resolve().parents[1]
manifest=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'))
assert len(manifest['files'])==1168
assert all((root/f['path']).is_file() and (root/f['path']).stat().st_size==f['bytes'] for f in manifest['files'])
images=[image for image in bpy.data.images if image.source=='SEQUENCE'];assert len(images)==16
for image in images:
    assert image.filepath.startswith('//')
    assert Path(bpy.path.abspath(image.filepath)).resolve().is_relative_to(root)
assert not any([bpy.app.handlers.frame_change_pre,bpy.app.handlers.frame_change_post,bpy.app.handlers.render_pre,bpy.app.handlers.render_post])
assert not any(name.startswith(('ges_next','satpy','rasterio')) for name in sys.modules)
assert not bpy.context.preferences.filepaths.use_scripts_auto_execute
scene=bpy.context.scene;camera=scene.camera
assert scene['earthstudio_camera_edit_mode']=='native_transform_lens_30fps'
assert not camera.hide_select and camera.select_get() and scene.view_layers[0].objects.active==camera
assert camera.animation_data.action!=camera.data.animation_data.action
assert scene.keying_sets.active.bl_label=='记录自由相机 · 位置旋转焦距'
assert all(p.id in (camera,camera.data) for p in scene.keying_sets.active.paths)
control=bpy.data.objects[camera['earthstudio_controller']];paths=json.loads(control['earthstudio_parameter_paths'])
shell=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
nodes=shell.data.materials[0].node_tree
switch_drivers={key:next(d for d in nodes.animation_data.drivers if any(v.targets[0].id==control and v.targets[0].data_path==paths['["'+key+'"]'] for v in d.driver.variables)) for key in ['blueAtmosphere','nightAirglow']}
states=[]
scene.frame_set(scene.frame_end)
for blue,night in [(False,False),(True,False),(False,True),(True,True)]:
    for key,value in [('blueAtmosphere',blue),('nightAirglow',night)]:
        owner,attr=paths['["'+key+'"]'].rsplit('.',1);setattr(control.path_resolve(owner),attr,value)
    control.update_tag();bpy.context.view_layer.update()
    values={key:nodes.path_resolve(driver.data_path) for key,driver in switch_drivers.items()}
    assert values==dict(blueAtmosphere=float(blue),nightAirglow=float(night)),values
    states.append(values)

# Record edited pose using the saved keying set, without importing application code.
scene.frame_set(601);before=camera.matrix_world.copy();lens=camera.data.lens
camera.location.x+=.25;camera.rotation_quaternion=camera.rotation_quaternion@Quaternion((0,0,1),.1);camera.data.lens+=3
camera.update_tag();bpy.context.view_layer.update()
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
with bpy.context.temp_override(area=area,region=region):assert bpy.ops.anim.keyframe_insert()=={'FINISHED'}
scene.frame_set(602);scene.frame_set(601)
assert (camera.matrix_world.translation-before.translation).length>.24 and abs(camera.data.lens-lens-3)<1e-4
assert abs(control.path_resolve(paths['["weatherHours"]'])-12)<1e-4
scene.render.engine='CYCLES';scene.cycles.device='GPU'
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for device in prefs.devices:device.use=device.type=='OPTIX'
scene.cycles.samples=4;scene.cycles.adaptive_min_samples=4
scene.render.resolution_x,scene.render.resolution_y=640,360;scene.render.resolution_percentage=100
scene.render.filepath=str(out/'reopened_edited_pose.png');bpy.ops.render.render(write_still=True)
(out/'verification.json').write_text(json.dumps(dict(relocated_project=bpy.data.filepath,assets_checked=1168,relative_image_sequences=16,autoexec_disabled=True,no_scientific_runtime=True,no_custom_handlers=True,free_camera_selected_and_selectable=True,saved_keying_set_native_edit=True,independent_atmosphere_switch_states=states,weather_clock_preserved=True,edited_pose_rendered=True),ensure_ascii=False,indent=2),encoding='utf-8')
print('REOPENED_RELOCATED_FREE_CAMERA_EDIT_VERIFIED',flush=True)
