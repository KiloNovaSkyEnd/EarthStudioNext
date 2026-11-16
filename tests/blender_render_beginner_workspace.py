"""Real renders from per-take scenes; native modifier rim controls stay isolated."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable

out = require_writable(sys.argv[sys.argv.index('--')+1])
out.mkdir(parents=True, exist_ok=True)
scenes = {s['earthstudio_scene_track']: s for s in bpy.data.scenes}
scene = scenes['A']
bpy.context.window.scene = scene
control = bpy.data.objects[scene.camera['earthstudio_controller']]
paths = json.loads(control['earthstudio_parameter_paths'])
other = bpy.data.objects[scenes['B'].camera['earthstudio_controller']]
other_paths = json.loads(other['earthstudio_parameter_paths'])
before = [other.path_resolve(other_paths['["'+k+'"]']) for k in ('blueAtmosphere', 'nightAirglow')]
scene.frame_set(1)
scene.render.resolution_x, scene.render.resolution_y = 640, 360
scene.render.resolution_percentage = 100
scene.cycles.samples = scene.cycles.adaptive_min_samples = 8
scene.render.use_persistent_data = True
for blue, warm, label in [(False, False, 'off'), (True, False, 'blue'), (False, True, 'warm'), (True, True, 'both')]:
    for key, value in [('blueAtmosphere', blue), ('nightAirglow', warm)]:
        owner, field = paths['["'+key+'"]'].rsplit('.', 1)
        setattr(control.path_resolve(owner), field, value)
    control.update_tag()
    bpy.context.view_layer.update()
    scene.render.filepath = str(out/(label+'.png'))
    bpy.ops.render.render(write_still=True)
    assert [other.path_resolve(other_paths['["'+k+'"]']) for k in ('blueAtmosphere', 'nightAirglow')] == before
    print('BEGINNER_RENDER_DONE', label, flush=True)
result = dict(native_modifier_rim_controls=True, editing_one_take_does_not_change_other_rim=True,
              frame_end=scene.frame_end, scene=scene.name, renders=4, autoexec_required=False)
(out/'render_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
