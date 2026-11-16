"""Headless footprint preparation and final scene assembly, independent of UI."""
import argparse
import json
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))

parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
parser.add_argument('--stage',choices=('request','assemble'),required=True)
parser.add_argument('--result'); args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
root=Path(args.root)
if args.stage=='request':
    from blender_support.camera_request import write
    request=write(bpy.context.scene,all_nodes=True)
    (root/'reports/sequence_camera_request.json').write_text(json.dumps({'request':str(request)}),encoding='utf-8')
    print('CAMERA_REQUEST',request,flush=True)
else:
    from blender_support.import_tiles import load
    load(args.result)
    target=root/'exports/earth_camera_sequence_v1/Earth_20220831_Camera_Ready.blend'
    if target.exists(): raise FileExistsError('Existing final scene preserved')
    scene=bpy.context.scene
    from blender_support.gpu import configure
    configure(scene)
    assets=json.loads((root/'processed/stock_geocolor/blender_sequence_assets/scene_assets.json').read_text(encoding='utf-8'))
    engine_command=assets['engine_command']
    if len(engine_command)==1 and Path(engine_command[0]).name=='EarthScience.Cuda.exe':
        # A fresh user Blender process also needs the launcher's CUDA path setup.
        engine_command=[str(Path(__file__).resolve().parents[2]/'EarthScience.Engine.exe')]
    scene['earth_engine_command']=json.dumps(engine_command)
    scene['earth_engine_cwd']=assets['engine_cwd']
    scene['earth_blender_scripts']=str(Path(__file__).resolve().parent)
    scene['prepared_camera_request']=str(args.result)
    scene['native_preparation']='Prepared for this camera path. Re-prepare after changing view or render resolution. Raw archive retains all supported source grids.'
    scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGB'
    scene.render.filepath=str(target.parent/'user_renders/frame_')
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(target))
    print('CAMERA_READY',target,flush=True)
