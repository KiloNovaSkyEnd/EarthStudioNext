"""Render primary-colour fixtures to verify exact file selection at hold edges."""
import argparse
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0,str(Path(__file__).resolve().parent))
from blender_support.materials import weather


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--folder',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]); folder=Path(args.folder)
    bpy.ops.wm.read_factory_settings(use_empty=True); scene=bpy.context.scene
    scene.render.engine='CYCLES'; scene.cycles.samples=1
    scene.render.resolution_x=32; scene.render.resolution_y=32; scene.render.resolution_percentage=100
    scene.view_settings.view_transform='Standard'; scene.view_settings.look='None'
    scene.world=bpy.data.worlds.new('Black'); scene.world.use_nodes=True
    scene.world.node_tree.nodes.get('Background').inputs[0].default_value=(0,0,0,1)
    bpy.ops.mesh.primitive_plane_add(size=2)
    bpy.context.object.data.materials.append(weather('Fixture',folder/'weather_0001.png',3,32))
    camera=bpy.data.objects.new('Camera',bpy.data.cameras.new('Camera')); scene.collection.objects.link(camera); scene.camera=camera
    camera.location=(0,0,3); camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.type='ORTHO'; camera.data.ortho_scale=1.8
    checks=[]
    for frame,channel in ((-1,0),(0,0),(1,0),(32,0),(33,1),(64,1),(65,2),(96,2),(97,2)):
        scene.frame_set(frame); path=folder/f'render_{frame:04d}.png'; scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
        image=bpy.data.images.load(str(path),check_existing=False)
        rgb=list(image.pixels[(16*32+16)*4:(16*32+16)*4+3])
        passed=rgb[channel]>.99 and all(c<.01 for i,c in enumerate(rgb) if i!=channel)
        checks.append({'frame':frame,'expected_primary_channel':channel,'rgb':rgb,'passed':passed})
    (folder/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    if not all(c['passed'] for c in checks): raise AssertionError('Blender sequence selected the wrong UTC/source file')
    print('NINE_SEQUENCE_BOUNDARIES_PASSED',flush=True)


if __name__=='__main__': main()
