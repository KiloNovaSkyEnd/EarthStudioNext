"""Reopen a saved regional scene and validate native relative image dependencies."""
import json
from pathlib import Path
import bpy

scene=bpy.context.scene
images=[image for image in bpy.data.images if image.source in ('FILE','SEQUENCE')]
records=[]
for image in images:
    resolved=Path(bpy.path.abspath(image.filepath))
    if not image.filepath.startswith('//') or not resolved.is_file():
        raise ValueError('Native relative dependency does not resolve: '+str(resolved))
    records.append({'relative':image.filepath,'resolved':str(resolved),'size':list(image.size)})
if not records or not all(record['size']==[1122,1122] for record in records):
    raise ValueError('Expected original native-page dependencies')
root=Path(scene['earth_project_root'])
(root/'reports/native_portable_qualification_v20.json').write_text(json.dumps({
    'scene':bpy.data.filepath,'native_images':records,'all_dependencies_relative_and_present':True,
    'global_delivery_complete':False,'limits':'Regional scene dependency qualification only'},indent=2),encoding='utf-8')
scene.frame_set(1)
scene.render.filepath=str(root/'reports/native_portable_render_v20.png')
bpy.ops.render.render(write_still=True)
