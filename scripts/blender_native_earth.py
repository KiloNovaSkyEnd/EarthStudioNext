"""Final native-only Blender Earth; no coarse global imagery is loaded."""
import argparse
import json
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_support.geometry import mesh_patch
from blender_support.camera import create as camera
from blender_support.rim import create as rim
from blender_support.gpu import configure
from blender_support.native_globe import load

parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True); parser.add_argument('--assets')
parser.add_argument('--scene-name')
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
root=Path(args.root); output=root/'exports/earth_native_only_v1'
assets=json.loads(Path(args.assets or output/'native_assets.json').read_text(encoding='utf-8'))
target=output/('Earth_Native_73_UTC.blend' if assets.get('global_native_precomputed') else 'Native_qualification.blend')
if args.scene_name:
    if Path(args.scene_name).name!=args.scene_name or not args.scene_name.endswith('.blend'):
        raise ValueError('Native scene name must be a local .blend filename')
    target=output/args.scene_name
if target.exists(): raise FileExistsError('Existing native scene preserved')
bpy.ops.wm.read_factory_settings(use_empty=True); scene=bpy.context.scene; configure(scene)
scene.render.resolution_x=1920; scene.render.resolution_y=1080; scene.render.resolution_percentage=100
scene.render.fps=24; scene.frame_start=1; scene.frame_end=len(assets['nodes'])*assets['hold']
scene.view_settings.view_transform='Standard'; scene.view_settings.look='None'; scene.view_settings.exposure=0
scene.world=bpy.data.worlds.new('Space'); scene.world.use_nodes=True
scene.world.node_tree.nodes.get('Background').inputs[0].default_value=(0,0,0,1)
base=mesh_patch('Neutral missing-data indicator · excluded poles, no ground texture',(-180,-90,180,90),6370.8,720,360)
material=bpy.data.materials.new('Missing observations only'); material.use_nodes=True
tree=material.node_tree; tree.nodes.clear(); emission=tree.nodes.new('ShaderNodeEmission')
emission.inputs['Color'].default_value=(.008,.008,.008,1)
tree.links.new(emission.outputs[0],tree.nodes.new('ShaderNodeOutputMaterial').inputs['Surface'])
base.data.materials.append(material)
camera(scene,full=True)
load(scene,root,assets)
frames=[{'sun':n['sun'],'nominal_utc':n['nominal_utc']} for n in assets['nodes']]
rim(scene,frames,assets['hold'])
scene['weather_utc_nodes']=json.dumps([n['nominal_utc'] for n in assets['nodes']]); scene['weather_hold_frames']=assets['hold']
scene['earth_project_root']=str(root); scene['earth_blender_scripts']=str(Path(__file__).resolve().parent)
scene['earth_engine_command']=json.dumps([assets['engine']]); scene['earth_engine_cwd']=str(root)
scene['acceptance']='Native-only assets; final geographic, temporal and visual acceptance pending.'
scene['seviri']='Observed natural-colour adaptation, not stock SEVIRI GeoColor.'
scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGB'
if not assets.get('global_native_precomputed',False):
    # Regional qualification opens on its actual native page, never as a globe claim.
    from blender_support.geometry import position
    c,r=assets['cells'][0]; lon=-180+(c+.5)*5; lat=-90+(r+.5)*5
    scene.camera.animation_data_clear()
    for constraint in list(scene.camera.constraints): scene.camera.constraints.remove(constraint)
    scene.camera.location=position(lon,lat,7600)
    scene.camera.rotation_euler=(position(lon,lat,6371)-scene.camera.location).to_track_quat('-Z','Y').to_euler()
    scene.camera.data.lens=85
scene.render.filepath=str(output/'user_renders/frame_'); scene.frame_set(1)
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_perspective='CAMERA'
            area.spaces.active.shading.type='MATERIAL'
            area.spaces.active.shading.use_scene_world=True; area.spaces.active.shading.use_scene_lights=True
output.mkdir(parents=True,exist_ok=True)
for image in bpy.data.images:
    if image.source in ('FILE','SEQUENCE') and image.filepath:
        image.filepath=bpy.path.relpath(image.filepath,start=str(output))
bpy.ops.wm.save_as_mainfile(filepath=str(target),relative_remap=False)
print('NATIVE_BLENDER_READY',target,flush=True)
