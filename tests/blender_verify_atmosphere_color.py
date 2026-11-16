"""Reopen V4: verify every new control animates, then measure actual render changes."""
import json
from pathlib import Path
import sys
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.layered_atmosphere import CONTROLS
from ges_next.isolation import require_writable

out = require_writable(sys.argv[sys.argv.index('--')+1])
out.mkdir(parents=True, exist_ok=True)
records = []

def set_value(control, paths, key, value):
    owner, attr = paths['["'+key+'"]'].rsplit('.', 1)
    setattr(control.path_resolve(owner), attr, value)
    control.update_tag()
    bpy.context.view_layer.update()

for scene in bpy.data.scenes:
    bpy.context.window.scene = scene
    scene.frame_set(1)
    control = bpy.data.objects[scene.camera['earthstudio_controller']]
    paths = json.loads(control['earthstudio_parameter_paths'])
    proxy = next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
    tree = proxy.data.materials[0].node_tree
    assert sum(n.bl_idname == 'ShaderNodeHueSaturation' for n in tree.nodes) == 2
    for curve in tree.animation_data.drivers:
        assert curve.driver.variables[0].targets[0].id == control
    original = control.animation_data.action
    copy = original.copy()
    control.animation_data.action = copy
    control.animation_data.action_slot = copy.slots[0]
    for key, label, minimum, maximum, default in CONTROLS:
        path = paths['["'+key+'"]']
        assert abs(control.path_resolve(path)-default) < 1e-6, (scene.name, key)
        set_value(control, paths, key, default)
        control.keyframe_insert(path, frame=1)
        changed = 90 if key.endswith('Hue') else 1.7
        set_value(control, paths, key, changed)
        control.keyframe_insert(path, frame=11)
    scene.frame_set(1)
    for key, _, _, _, default in CONTROLS:
        assert abs(control.path_resolve(paths['["'+key+'"]'])-default) < 1e-5
    scene.frame_set(11)
    for key, _, _, _, _ in CONTROLS:
        assert abs(control.path_resolve(paths['["'+key+'"]'])-(90 if key.endswith('Hue') else 1.7)) < 1e-5
    control.animation_data.action = original
    control.animation_data.action_slot = original.slots[0]
    scene.frame_set(1)
    for key, _, _, _, default in CONTROLS:
        set_value(control, paths, key, default)
    records.append(dict(scene=scene.name, ten_controls_animate=True, own_controller_drivers=True))

scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'A')
bpy.context.window.scene = scene
control = bpy.data.objects[scene.camera['earthstudio_controller']]
paths = json.loads(control['earthstudio_parameter_paths'])
scene.render.resolution_x, scene.render.resolution_y = 640, 360
scene.render.resolution_percentage = 100
scene.cycles.samples = 32
scene.cycles.use_denoising = False
scene.render.use_persistent_data = True

def reset(blue, warm):
    for key, _, _, _, default in CONTROLS:
        set_value(control, paths, key, default)
    set_value(control, paths, 'blueAtmosphere', blue)
    set_value(control, paths, 'nightAirglow', warm)

def render(name):
    path = out/(name+'.png')
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(path), check_existing=False)
    data = np.array(image.pixels[:], dtype=np.float32).reshape(360, 640, 4)[..., :3]
    bpy.data.images.remove(image)
    print('COLOR_RENDER', name, flush=True)
    return data

baselines = {}
for blue, warm, name in [(False, False, 'off'), (True, False, 'blue'), (False, True, 'warm'), (True, True, 'both')]:
    reset(blue, warm)
    baselines[name] = render(name)
changes = []
for key, _, _, _, _ in CONTROLS:
    blue = key.startswith('blue')
    reset(blue, not blue)
    value = 100 if key.endswith('Hue') else 0 if key.endswith('Saturation') else 2
    set_value(control, paths, key, value)
    pixels = render(key)
    diff = np.abs(pixels-baselines['blue' if blue else 'warm'])
    assert float(diff.max()) > .001, (key, float(diff.max()))
    changes.append(dict(key=key, tested_value=value, max_change=float(diff.max()), mean_change=float(diff.mean())))
# Saturation/brightness/thickness must have no effect when both layers are off.
reset(False, False)
for key, _, _, maximum, _ in CONTROLS:
    set_value(control, paths, key, maximum)
off = render('off_extreme_controls')
assert float(np.abs(off-baselines['off']).max()) <= 1/255+.0001
assert np.max(np.abs(baselines['both']-baselines['blue'])) > .001
assert np.max(np.abs(baselines['both']-baselines['warm'])) > .001
report = dict(scenes=records, actual_render_controls=changes, separate_switches=True,
              disabled_controls_leave_surface_unchanged=True, autoexec_required=False)
(out/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS all ten controls: native animation, independent drivers, actual rendered response and disabled-layer isolation', flush=True)
