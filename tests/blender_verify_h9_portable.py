"""Standalone Blender-only relocation test; no project modules imported."""
from pathlib import Path
import bpy,json,sys,math
out=Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(exist_ok=True,parents=True)
root=Path(bpy.data.filepath).parent.resolve()
manifest=json.loads((root/'sequence_manifest.json').read_text())
assert len(manifest['files'])==1168
assert all((root/row['path']).is_file() for row in manifest['files'])
assert not bpy.app.handlers.frame_change_pre and not bpy.app.handlers.frame_change_post
assert not bpy.app.handlers.render_pre and not bpy.app.handlers.render_post
images=[i for i in bpy.data.images if i.source=='SEQUENCE'];assert len(images)==16
for image in images:
    assert image.filepath.startswith('//')
    assert Path(bpy.path.abspath(image.filepath)).resolve().is_relative_to(root)
scene=bpy.context.scene
scene.render.engine='CYCLES';scene.cycles.device='GPU'
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for device in prefs.devices:device.use=device.type=='OPTIX'
scene.cycles.samples=4;scene.cycles.adaptive_min_samples=4
scene.render.resolution_x,scene.render.resolution_y=320,180;scene.render.resolution_percentage=100
scene.frame_set(scene.frame_end)
scene.render.filepath=str(out/'relocated_end.png');bpy.ops.render.render(write_still=True)
report=dict(relocated_package=str(root),all1168_images_present=True,relative_native_sequences=16,
    no_frame_or_render_handlers=True,blender_only_imports=True,autoexec_disabled=not bpy.context.preferences.filepaths.use_scripts_auto_execute,
    scientific_runtime_required=False,webpage_required=False,rendered_later_weather_node=True)
(out/'portability.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('PORTABLE_BLENDER_ONLY_RENDER_PASSED',flush=True)
