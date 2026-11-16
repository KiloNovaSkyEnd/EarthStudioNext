"""Native page sequences on a complete sphere, with camera horizon culling."""
import math
from pathlib import Path
import bpy
from .geometry import mesh_patch
from .materials import weather


def cull_behind_earth(obj,scene,bounds):
    w,s,e,n=bounds; lon=math.radians((w+e)/2); lat=math.radians((s+n)/2)
    nx,ny,nz=math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)
    for attribute in ('hide_render','hide_viewport'):
        curve=obj.driver_add(attribute); driver=curve.driver
        for index,name in enumerate(('cx','cy','cz')):
            variable=driver.variables.new(); variable.name=name; variable.type='SINGLE_PROP'
            target=variable.targets[0]; target.id_type='SCENE'; target.id=scene
            # RNA matrix paths expose column-major indices (unlike mathutils).
            target.data_path=f'camera.matrix_world[3][{index}]'
        driver.expression=f'({nx}*cx+{ny}*cy+{nz}*cz+sqrt(cx*cx+cy*cy+cz*cz)*0.065)<6371'


def load(scene,root,assets):
    root=Path(root); nodes=assets['nodes']; hold=assets['hold']
    namespace=assets.get('namespace','native_earth_v1')
    import json
    for c,r in assets['cells']:
        folder=root/'processed'/namespace/'cells'/f'c{c:02d}_r{r:02d}'
        record=json.loads((folder/f"weather_{nodes[0]['index']:04d}.json").read_text(encoding='utf-8'))
        if not record.get('native_only') or record.get('proxy'):
            raise ValueError('Native-only globe refuses a proxy texture')
        obj=mesh_patch(f'Native weather {c:02d} {r:02d}',record['bounds'],6371.012,20,20)
        inset=record['halo_pixels']/record['size']
        for loop in obj.data.uv_layers.active.data:
            loop.uv=(inset+loop.uv.x*(1-2*inset),inset+loop.uv.y*(1-2*inset))
        obj.data.materials.append(weather(f'Native sequence {c:02d} {r:02d}',record['texture'],len(nodes),hold,transparent_missing=True))
        obj['native_only']=True; obj['cell']=f'{c},{r}'
        obj['source_metadata']=str(folder)
        cull_behind_earth(obj,scene,record['bounds'])
    scene['earth_native_only']=True
    scene['global_native_precomputed']=bool(assets.get('global_native_precomputed',False))
