"""Compare native Blender driver rigs against real Cesium samples, then edit/retime."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from scripts.blender_support.editable_camera import curves
from ges_next.camera import horizontal_lens_mm

args = sys.argv[sys.argv.index('--')+1:]
bundle = json.loads(Path(args[0]).read_text(encoding='utf-8'))
scene = bpy.context.scene
rigs = {o['earthstudio_editable_camera']: o for o in scene.objects if 'earthstudio_editable_camera' in o}
controls = {o['earthstudio_editable_track']: o for o in scene.objects if 'earthstudio_editable_track' in o}
eligible = [t for t in bundle['tracks'] if t.get('keyframeTrack', {}).get('keys') and all(k.get('orbit') for k in t['keyframeTrack']['keys'])]
assert len(rigs) == len(controls) == len(eligible)
assert len({o.animation_data.action.as_pointer() for o in controls.values()}) == len(eligible)
assert scene.camera == rigs[bundle['timelineProject']['activeTrack']]
errors = {}
for track in bundle['tracks']:
    identity = track['keyframeTrack']['id']
    if identity not in rigs:
        continue
    camera = rigs[identity]
    maximum = dict(position_metres=0, direction=0, up=0, lens_mm=0)
    for sample in track['samples']:
        f = 1+sample['seconds']*track['fps']
        scene.frame_set(math.floor(f), subframe=f-math.floor(f))
        matrix = camera.matrix_world
        maximum['position_metres'] = max(maximum['position_metres'], (matrix.translation-Vector(sample['position'])/1e6).length*1e6)
        maximum['direction'] = max(maximum['direction'], (-(matrix.to_3x3() @ Vector((0, 0, 1)))-Vector(sample['direction'])).length)
        maximum['up'] = max(maximum['up'], ((matrix.to_3x3() @ Vector((0, 1, 0)))-Vector(sample['up'])).length)
        maximum['lens_mm'] = max(maximum['lens_mm'], abs(camera.data.lens-horizontal_lens_mm(sample)))
    print(identity, maximum, flush=True)
    assert maximum['position_metres'] < 20, maximum
    assert maximum['direction'] < 3e-6 and maximum['up'] < 3e-6, maximum
    assert maximum['lens_mm'] < .0002, maximum
    assert len(curves(controls[identity])) == 7
    assert all(len(c.keyframe_points) < len(track['samples'])/4 for c in curves(controls[identity]))
    errors[identity] = maximum

fixture_checks = {'A', 'B', 'C'}.issubset(rigs)
if fixture_checks:
    # Same path, different durations: inspect matching fractions, not matching frame numbers.
    for fraction in [0, .1, .25, .5, .75, .9, 1]:
        scene.frame_set(round(1+fraction*12*30))
        pose = rigs['B'].matrix_world.copy()
        scene.frame_set(round(1+fraction*30*30))
        assert max(abs(pose[r][c]-rigs['C'].matrix_world[r][c]) for r in range(4) for c in range(4)) < 1e-5
    
    # Save original actions so validation mutations never reach the delivered project.
    original = controls['B'].animation_data.action
    controls['B'].animation_data.action = original.copy()
    scene.frame_set(1)
    other_pose = rigs['A'].matrix_world.copy()
    before = rigs['B'].matrix_world.copy()
    control = controls['B']
    control['rangeKm'] = 7000.
    control.keyframe_insert('["rangeKm"]', frame=1)
    scene.frame_set(2)
    scene.frame_set(1)
    assert (rigs['B'].matrix_world.translation-before.translation).length > .9
    assert max(abs(other_pose[r][c]-rigs['A'].matrix_world[r][c]) for r in range(4) for c in range(4)) < 1e-8
    control.animation_data.action = original
    
    # Whole action retime around frame 1 preserves the path and its speed style.
    control.animation_data.action = original.copy()
    for curve in curves(control):
        for point in curve.keyframe_points:
            point.co.x = 1+(point.co.x-1)*2
            point.handle_left.x = 1+(point.handle_left.x-1)*2
            point.handle_right.x = 1+(point.handle_right.x-1)*2
    for frame in [1, 73, 181, 289, 361]:
        scene.frame_set(frame)
        # Retimed B has duration 24; unchanged C has duration 30.
        b = rigs['B'].matrix_world.copy()
        scene.frame_set(round(1+(frame-1)*30/24))
        assert max(abs(b[r][c]-rigs['C'].matrix_world[r][c]) for r in range(4) for c in range(4)) < 2e-5
    control.animation_data.action = original
    scene.frame_set(1)
fallbacks = [o for o in scene.objects if 'unavailable' in o.get('earthstudio_edit_mode', '')]
assert len(fallbacks) == len(bundle['tracks'])-len(eligible)
report = dict(editable_rigs=len(eligible), free_pose_fallbacks=len(fallbacks), errors=errors,
              independent_actions=True, parameter_edit_isolated=True if fixture_checks else None,
              same_path_different_durations=True if fixture_checks else None, native_curve_retime=True if fixture_checks else None,
              world_model='WGS84 ECEF', weather_materials_included=not scene.get('earthstudio_camera_only', True))
require_writable(args[1]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS editable rigs and all samples'+('; independent edits and native retiming' if fixture_checks else ''), flush=True)
