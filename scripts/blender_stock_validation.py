"""Editable Blender scene from stock/explicitly labelled SEVIRI pilot assets."""
import argparse
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_support.materials import weather
from blender_support.rim import create as create_rim
from blender_support.geometry import mesh_patch


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--sequence',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root=Path(args.root).resolve()
    assets_file=root/('processed/stock_geocolor/blender_sequence_assets/scene_assets.json' if args.sequence else
                      'processed/stock_geocolor/blender_assets/scene_assets.json')
    assets=json.loads(assets_file.read_text(encoding='utf-8'))
    out=root/('exports/earth_camera_sequence_v1' if args.sequence else 'exports/stock_pilot_v1')
    out.mkdir(parents=True,exist_ok=True)
    target=out/('Earth_20220831_73_UTC.blend' if args.sequence else 'earth_stock_pilot.blend')
    if target.exists(): raise FileExistsError('Existing .blend preserved; select a new versioned export')
    bpy.ops.wm.read_factory_settings(use_empty=True); scene=bpy.context.scene
    scene.render.engine='CYCLES'; scene.cycles.samples=8
    scene.render.resolution_x=1920 if args.sequence else 960
    scene.render.resolution_y=1080 if args.sequence else 540; scene.render.resolution_percentage=100
    scene.render.fps=24; hold=4 if args.sequence else 32
    total=len(assets['frames']); scene.frame_start=1; scene.frame_end=total*hold
    scene.view_settings.view_transform='Standard'; scene.view_settings.look='None'; scene.view_settings.exposure=0
    scene.world=bpy.data.worlds.new('Space'); scene.world.use_nodes=True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value=(0,0,0,1)
    earth=mesh_patch('Observed weather · grey means missing',(-180,-90,180,90),6371,720,360)
    earth.data.materials.append(weather('Satpy display · no second illumination',assets['frames'][0]['file'],total,hold))
    rim=create_rim(scene,assets['frames'],hold)
    if not args.sequence:
        native=json.loads(Path(assets['native_mesh']).read_text(encoding='utf-8'))
        cols,rows=native['cols'],native['rows']
        faces=[(y*(cols+1)+x,y*(cols+1)+x+1,(y+1)*(cols+1)+x+1,(y+1)*(cols+1)+x) for y in range(rows) for x in range(cols)]
        mesh=bpy.data.meshes.new('Native sensor navigation'); mesh.from_pydata(native['vertices'],[],faces); mesh.update()
        uv=mesh.uv_layers.new(name='Native sensor UV')
        for polygon in mesh.polygons:
            polygon.use_smooth=True
            for loop in polygon.loop_indices:
                vertex=mesh.loops[loop].vertex_index; uv.data[loop].uv=(vertex%(cols+1)/cols,vertex//(cols+1)/rows)
        detail=bpy.data.objects.new('One UTC native tile · 127E 25N · not global',mesh); scene.collection.objects.link(detail)
        detail.data.materials.append(weather('Same UTC native pixels',assets['native_texture'],transparent_missing=True))
        for frame,hidden in ((1,True),((total-1)*hold,True),((total-1)*hold+1,False)):
            detail.hide_render=hidden; detail.hide_viewport=hidden
            detail.keyframe_insert('hide_render',frame=frame); detail.keyframe_insert('hide_viewport',frame=frame)
    from blender_support.camera import create as create_camera
    create_camera(scene,full=args.sequence)
    scene['weather_utc_nodes']=json.dumps([f['nominal_utc'] for f in assets['frames']])
    scene['weather_hold_frames']=hold
    scene['earth_project_root']=str(root)
    scene['earth_blender_scripts']=str(Path(__file__).resolve().parent)
    scene['earth_engine_command']=json.dumps(assets.get('engine_command',[]))
    scene['earth_engine_cwd']=assets.get('engine_cwd',str(root))
    scene['acceptance']=('73 observation nodes. Native details must be prepared for the final camera. Global/native acceptance remains pending.' if args.sequence else
                         'PILOT ONLY: three weather nodes, one native tile. No complete global/native acceptance.')
    scene['seviri']='Natural colour + Satpy night compositors, explicitly adapted; not stock SEVIRI GeoColor.'
    scene['atmosphere']='World-space tangent-height Gaussian display; Blender port requires visual acceptance.'
    scene['missing']='Neutral grey indicates unsupported or missing observations; no static daytime fill.'
    scene.frame_set(1)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.shading.type='MATERIAL'
                area.spaces.active.shading.use_scene_world=True
                area.spaces.active.shading.use_scene_lights=True
    bpy.ops.wm.save_as_mainfile(filepath=str(target))
    report={'scene':str(target),'assets':str(assets_file),
        'weather_nodes':total,'full_73_nodes':total==73,'global_native_passed':False,'visual_acceptance_passed':False}
    (out/'scene_manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if args.render:
        scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGB'
        scene.render.filepath=str(out/'frames/frame_'); (out/'frames').mkdir(exist_ok=True)
        bpy.ops.render.render(animation=True)
    print('BLENDER_STOCK_PILOT',target,flush=True)


if __name__=='__main__': main()
