"""Exercise native page drivers with changed camera position AND active camera."""
import json
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_support.geometry import position
scene=bpy.context.scene; scene.frame_set(1)
from blender_support.native_globe import cull_behind_earth
camera=scene.camera; camera.animation_data_clear()
for constraint in list(camera.constraints): camera.constraints.remove(constraint)
page=next(obj for obj in scene.objects if obj.get('native_only'))
page.driver_remove('hide_render'); page.driver_remove('hide_viewport')
cull_behind_earth(page,scene,(125,20,130,25))
results=[]
for lon in (127.5,-52.5,127.5):
    camera.location=position(lon,22.5,7600); bpy.context.view_layer.update()
    hidden=page.evaluated_get(bpy.context.evaluated_depsgraph_get()).hide_render
    results.append(bool(hidden))
assert results==[False,True,False],results
other=bpy.data.objects.new('Independent user camera',camera.data.copy()); scene.collection.objects.link(other)
other.location=position(-52.5,22.5,7600); scene.camera=other; bpy.context.view_layer.update()
assert page.evaluated_get(bpy.context.evaluated_depsgraph_get()).hide_render
scene.camera=camera; bpy.context.view_layer.update()
camera.rotation_euler=(position(127.5,22.5,6371)-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.lens=85; scene.render.resolution_x=960; scene.render.resolution_y=540
root=Path(scene['earth_project_root']); scene.render.filepath=str(root/'reports/native_only_page_blender.png')
bpy.ops.render.render(write_still=True)
(root/'reports/native_only_blender_qualification.json').write_text(json.dumps({
    'camera_position_culling':results,'active_camera_switch_passed':True,
    'proxy_images_loaded':False,'native_pages':1,'global_delivery_complete':False}),encoding='utf-8')
