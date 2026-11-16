"""Build a measured-weather globe feasibility scene from explicit prepared assets.

Global proxy and a separately sampled native-detail region animate together.
Surface-composite geometry only: no claim of retrieved 3D cloud interiors.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector


def position(lon,lat,radius):
    lon,lat=map(math.radians,(lon,lat))
    return Vector((radius*math.cos(lat)*math.cos(lon),radius*math.cos(lat)*math.sin(lon),radius*math.sin(lat)))


def mesh_patch(name,bounds,radius,cols,rows):
    w,s,e,n=bounds
    vertices=[position(w+(e-w)*x/cols,s+(n-s)*y/rows,radius) for y in range(rows+1) for x in range(cols+1)]
    faces=[]
    for y in range(rows):
        for x in range(cols):
            a=y*(cols+1)+x
            faces.append((a,a+1,a+cols+2,a+cols+1))
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(vertices,[],faces)
    mesh.update()
    uv=mesh.uv_layers.new(name='GeographicUV')
    for polygon in mesh.polygons:
        polygon.use_smooth=True
        for loop in polygon.loop_indices:
            vertex=mesh.loops[loop].vertex_index
            uv.data[loop].uv=(vertex%(cols+1)/cols,vertex//(cols+1)/rows)
    obj=bpy.data.objects.new(name,mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def sequence_material(name,first,frames,hold):
    material=bpy.data.materials.new(name)
    material.use_nodes=True
    nodes=material.node_tree.nodes
    nodes.clear()
    output=nodes.new('ShaderNodeOutputMaterial')
    emission=nodes.new('ShaderNodeEmission')
    texture=nodes.new('ShaderNodeTexImage')
    texture.image=bpy.data.images.load(str(first),check_existing=False)
    texture.image.source='SEQUENCE'
    texture.image.colorspace_settings.name='sRGB'
    texture.interpolation='Linear'
    texture.extension='EXTEND'
    user=texture.image_user
    user.frame_duration=frames
    user.frame_start=1
    user.use_auto_refresh=True
    # Each real weather observation is held; no invented intermediate weather.
    user.driver_add('frame_offset').driver.expression=f'floor((frame-1)/{hold})+1-frame'
    material.node_tree.links.new(texture.outputs['Color'],emission.inputs['Color'])
    material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
    return material


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--pilot',action='store_true')
    parser.add_argument('--render',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root=Path(args.root).resolve()
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    textures=root/'processed'/'textures'
    total=1 if args.pilot else len(plan['frames'])
    for label in ('global_proxy','east_asia_native_detail'):
        for i in range(1,total+1):
            path=textures/label/f'frame_{i:04d}.png'
            if not path.exists() or not path.with_suffix('.json').exists():
                raise FileNotFoundError('Sequence incomplete: '+str(path))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=16
    scene.render.resolution_x=1920
    scene.render.resolution_y=1080
    scene.render.resolution_percentage=100
    scene.render.fps=24
    scene.view_settings.view_transform='Standard'
    scene.view_settings.look='None'
    scene.view_settings.exposure=0
    scene.world=bpy.data.worlds.new('Space')
    scene.world.color=(0,0,0)
    hold=8
    scene.frame_start=1
    scene.frame_end=total*hold
    earth=mesh_patch('Earth_global_proxy',(-180,-90,180,90),6371,720,360)
    earth.data.materials.append(sequence_material('Global weather proxy',textures/'global_proxy/frame_0001.png',total,hold))
    patch=mesh_patch('East_Asia_native_detail',(120,5,150,40),6371.3,240,280)
    patch.data.materials.append(sequence_material('Native detail, same UTC',textures/'east_asia_native_detail/frame_0001.png',total,hold))
    camera_data=bpy.data.cameras.new('Camera')
    camera=bpy.data.objects.new('Camera',camera_data)
    scene.collection.objects.link(camera)
    scene.camera=camera
    camera.data.lens=40
    camera.data.clip_start=1
    camera.data.clip_end=100000
    final=scene.frame_end
    keys=[(1,-25,15,28000,-25,0),
          (max(2,round(final*.35)),-130,15,26000,-130,0),
          (max(3,round(final*.65)),135,20,23000,135,20),
          (max(4,final),136,27,7600,132,22)]
    for frame,lon,lat,radius,tlon,tlat in keys:
        camera.location=position(lon,lat,radius)
        camera.rotation_euler=(position(tlon,tlat,6371)-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.keyframe_insert('location',frame=frame)
        camera.keyframe_insert('rotation_euler',frame=frame)
    scene['GES_validation_root']=str(root)
    scene['GES_requested_time']='2022-08-31 11:00..23:00 UTC-06:00'
    scene['GES_actual_utc_sequence']=json.dumps(plan['frames'][:total])
    scene['GES_source_gap_report']=json.dumps(plan['failures'])
    scene['GES_detail_bounds']='120..150E / 5..40N; 8192x8192 regional, not a global 8K cap'
    scene['GES_cloud_geometry']='Surface composite; no retrieved volumetric cloud geometry'
    scene['GES_pilot_only']=args.pilot
    output=root/'exports'/('pilot' if args.pilot else 'global_sequence')
    output.mkdir(parents=True,exist_ok=True)
    target=output/'earth.blend'
    if target.exists():
        raise FileExistsError('Preserve completed Blender file; choose another export directory')
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(target))
    if args.render:
        scene.frame_set(scene.frame_end)
        scene.render.filepath=str(output/'near_preview.png')
        bpy.ops.render.render(write_still=True)
    report={'scene':str(target),'weather_frames':total,'display_frames':scene.frame_end,
            'proxy_shape':[1024,2048],'regional_detail_shape':[8192,8192],
            'source_gaps':plan['failures'],'textures_external':True,
            'preserves_all_native_band_caches':True,'not_full_volumetric_clouds':True}
    (output/'scene_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BLENDER VALIDATION SCENE',target,flush=True)


if __name__=='__main__':main()
