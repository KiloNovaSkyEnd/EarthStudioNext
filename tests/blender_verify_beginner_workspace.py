"""Saved V2 native UI controls, independent scenes, motion parity and edits."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.camera import horizontal_lens_mm
from ges_next.isolation import require_writable

bundle = json.loads(bpy.data.texts['camera_bundle.json'].as_string())
scenes = {s['earthstudio_scene_track']: s for s in bpy.data.scenes if 'earthstudio_scene_track' in s}
assert len(scenes) == len(bundle['tracks']) == 5
report = {}
for track in bundle['tracks']:
    identity = track['keyframeTrack']['id']
    scene = scenes[identity]
    bpy.context.window.scene = scene
    control = bpy.data.objects[scene.camera['earthstudio_controller']]
    paths = json.loads(control['earthstudio_parameter_paths'])
    assert scene.frame_end == math.ceil(1+track['samples'][-1]['seconds']*30)
    assert scene.frame_start == 1
    assert scene.view_layers[0].objects.active == control
    assert all(child.exclude for child in scene.view_layers[0].layer_collection.children if child.name.startswith('90｜'))
    assert all(control.path_resolve(paths['["'+key+'"]']) is not None for key in ('targetLon', 'targetLat', 'heading', 'pitch', 'rangeKm', 'roll', 'fov', 'blueAtmosphere', 'nightAirglow'))
    maximum = dict(position_metres=0, direction=0, up=0, lens_mm=0)
    for sample in track['samples']:
        frame = 1+sample['seconds']*track['fps']
        scene.frame_set(math.floor(frame), subframe=frame-math.floor(frame))
        matrix = scene.camera.matrix_world
        maximum['position_metres'] = max(maximum['position_metres'], (matrix.translation-Vector(sample['position'])/1e6).length*1e6)
        maximum['direction'] = max(maximum['direction'], (-(matrix.to_3x3() @ Vector((0, 0, 1)))-Vector(sample['direction'])).length)
        maximum['up'] = max(maximum['up'], ((matrix.to_3x3() @ Vector((0, 1, 0)))-Vector(sample['up'])).length)
        maximum['lens_mm'] = max(maximum['lens_mm'], abs(scene.camera.data.lens-horizontal_lens_mm(sample)))
    print(identity, maximum, flush=True)
    assert maximum['position_metres'] < 20, maximum
    assert maximum['direction'] < 3e-6 and maximum['up'] < 3e-6, maximum
    assert maximum['lens_mm'] < .0002, maximum
    report[identity] = dict(scene=scene.name, frame_end=scene.frame_end, samples=len(track['samples']), errors=maximum)
    scene.frame_set(1)
    shell = next(o for o in scene.objects if o.name.startswith('大气显示'))
    material = shell.material_slots[0].material
    for curve in material.node_tree.animation_data.drivers:
        for variable in curve.driver.variables:
            assert variable.targets[0].id == control

# A modifier input behaves like native animation: change + keyframe updates only this take.
scene = scenes['B']
bpy.context.window.scene = scene
control = bpy.data.objects[scene.camera['earthstudio_controller']]
paths = json.loads(control['earthstudio_parameter_paths'])
original = control.animation_data.action
control.animation_data.action = original.copy()
control.animation_data.action_slot = control.animation_data.action.slots[0]
scene.frame_set(1)
before = scene.camera.matrix_world.translation.copy()
other = scenes['A'].camera.matrix_world.copy()
path = paths['["rangeKm"]']
owner_path, field = path.rsplit('.', 1)
setattr(control.path_resolve(owner_path), field, 7000.)
control.keyframe_insert(path, frame=1)
scene.frame_set(2)
scene.frame_set(1)
assert (scene.camera.matrix_world.translation-before).length > .9
assert max(abs(other[r][c]-scenes['A'].camera.matrix_world[r][c]) for r in range(4) for c in range(4)) < 1e-8
control.animation_data.action = original
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            assert not area.spaces.active.overlay.show_overlays
            assert not area.spaces.active.show_gizmo
            assert area.spaces.active.region_3d.view_perspective == 'CAMERA'
        if area.type == 'PROPERTIES':
            assert area.spaces.active.context == 'MODIFIER'
assert len({s.render.filepath for s in scenes.values()}) == 5
output = require_writable(sys.argv[sys.argv.index('--')+1])
output.write_text(json.dumps(dict(scenes=report, independent_native_modifier_edit=True,
                                per_take_atmosphere=True, per_take_render_range=True,
                                clean_camera_view_saved=True, addon_required=False,
                                autoexec_required=False), ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS V2 beginner controls, 5 scenes, native edits, motion parity and clean UI settings', flush=True)
