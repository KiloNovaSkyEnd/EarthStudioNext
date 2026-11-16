"""Actual native-cell render diagnostic; never substitutes test imagery."""
import json
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_support.import_tiles import load
from blender_support.geometry import position
root=Path(sys.argv[sys.argv.index('--')+1])
result=root/'requests/qualification.result.json'; load(result)
for obj in bpy.data.objects:
    if obj.name.startswith('One UTC native tile'):
        obj.animation_data_clear(); obj.hide_render=True; obj.hide_viewport=True
scene=bpy.context.scene; scene.frame_set(80)
camera=bpy.data.objects.new('Native diagnostic camera',bpy.data.cameras.new('Native diagnostic'))
scene.collection.objects.link(camera); scene.camera=camera
camera.data.lens=85; camera.data.clip_end=100000
camera.location=position(127.5,22.5,7600)
camera.rotation_euler=(position(127.5,22.5,6371)-camera.location).to_track_quat('-Z','Y').to_euler()
scene.render.resolution_x=960; scene.render.resolution_y=540; scene.render.resolution_percentage=100
scene.cycles.samples=16
scene.render.image_settings.file_format='PNG'; scene.render.filepath=str(root/'reports/native_cell_blender_probe.png')
bpy.ops.render.render(write_still=True)
print('NATIVE_CELL_BLENDER_RENDERED',flush=True)
