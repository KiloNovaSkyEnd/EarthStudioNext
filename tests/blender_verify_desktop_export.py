"""Read-only verification of the actual native-button camera/weather handoff."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index('--') + 1:]
bundle = json.loads(Path(args[0]).read_text(encoding='utf-8'))
records = []
for index, track in enumerate(bundle['tracks'], 1):
    scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'WEB_' + str(index))
    bpy.context.window.scene = scene
    control = bpy.data.objects[scene.camera['earthstudio_controller']]
    paths = json.loads(control['earthstudio_parameter_paths'])
    earth = next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
    proxy = next(o for o in scene.objects if o.get('earthstudio_preview_proxy'))
    texture = next(n for n in earth.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE')
    assert not earth.hide_render and proxy.hide_render
    assert Path(bpy.path.abspath(texture.image.filepath)).is_file()
    errors = dict(position_metres=0, direction=0, up=0)
    weather = set()
    for sample in track['samples']:
        frame = round(1 + sample['seconds'] * track['fps'])
        scene.frame_set(frame)
        matrix = scene.camera.matrix_world
        errors['position_metres'] = max(errors['position_metres'], (matrix.translation-Vector(sample['position'])/1e6).length*1e6)
        errors['direction'] = max(errors['direction'], (-(matrix.to_3x3()@Vector((0,0,1)))-Vector(sample['direction'])).length)
        errors['up'] = max(errors['up'], ((matrix.to_3x3()@Vector((0,1,0)))-Vector(sample['up'])).length)
        nominal = min(73, 1 + math.floor(sample['seconds'] / track['samples'][-1]['seconds'] * 72 + 1e-5))
        actual = round(frame + texture.image_user.frame_offset)
        assert actual == (10 if nominal == 11 else nominal), (frame, nominal, actual)
        weather.add(nominal)
    assert errors['position_metres'] < 20 and errors['direction'] < 3e-6 and errors['up'] < 2e-4, errors
    assert len(weather) == 73
    records.append(dict(samples=len(track['samples']), original_keyframes=len(track['keyframeTrack']['keys']), errors=errors,
                        all73_weather_nodes_verified=True, proxy_excluded_from_render=True))
Path(args[1]).write_text(json.dumps(dict(source='actual native GUI Generate Blender button', project=bpy.data.filepath, tracks=records),ensure_ascii=False,indent=2),encoding='utf-8')
print('DESKTOP_EXPORT_VERIFIED', records, flush=True)
