"""Bake prepared native cell references into an editable, ordinary .blend."""
import json
from pathlib import Path
import bpy
from .geometry import mesh_patch
from .materials import weather


def load(result_file):
    result_file=Path(result_file).resolve()
    result=json.loads(result_file.read_text(encoding='utf-8'))
    name='Original pixels · '+result_file.stem
    if name in bpy.data.collections: return bpy.data.collections[name]
    replacing={tile['nominal_utc'] for tile in result['tiles']}
    for obj in bpy.data.objects:
        if obj.get('weather_utc') in replacing:
            obj.animation_data_clear(); obj.hide_render=True; obj.hide_viewport=True
    collection=bpy.data.collections.new(name); bpy.context.scene.collection.children.link(collection)
    shared={}
    for mesh in bpy.data.meshes:
        if 'earth_cell_bounds' in mesh: shared[mesh['earth_cell_bounds']]=mesh
    for index,tile in enumerate(result['tiles']):
        mesh_key=json.dumps(tile['bounds'])
        label=f"Original L{tile.get('level',0)} {tile['nominal_utc']} {tile['cell']}"
        if mesh_key in shared:
            obj=bpy.data.objects.new(label,shared[mesh_key]); bpy.context.collection.objects.link(obj)
        else:
            w,s,e,n=tile['bounds']
            obj=mesh_patch(label,tile['bounds'],6371.012,round((e-w)*4),round((n-s)*4))
            inset=tile['halo_pixels']/tile['size']
            for loop in obj.data.uv_layers.active.data:
                loop.uv=(inset+loop.uv.x*(1-2*inset),inset+loop.uv.y*(1-2*inset))
            obj.data['earth_cell_bounds']=mesh_key; shared[mesh_key]=obj.data
        for owner in list(obj.users_collection): owner.objects.unlink(obj)
        collection.objects.link(obj)
        material=weather(f"Original grid {index}",tile['texture'],transparent_missing=True)
        if not obj.data.materials: obj.data.materials.append(material)
        obj.material_slots[0].link='OBJECT'; obj.material_slots[0].material=material
        first,last=tile['display_frames']
        for frame,hidden in ((0,True),(first,False),(last+1,True)):
            obj.hide_render=hidden; obj.hide_viewport=hidden
            obj.keyframe_insert('hide_render',frame=frame); obj.keyframe_insert('hide_viewport',frame=frame)
        obj['source_metadata']=json.dumps(tile['sources']); obj['weather_utc']=tile['nominal_utc']
        obj['native_note']=tile['independent_rgb_resolution_m']
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    return collection
