"""Verify mode transitions on the actual imported project without saving changes."""
import importlib.util
import json
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preview_modes', root/'scripts/blender_preview_modes.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'WEB_1')
bpy.context.window.scene = scene
main = next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
proxy = next(o for o in scene.objects if o.get('earthstudio_preview_proxy'))
control, path = helper.controller(scene)
assert bool(control.path_resolve(path)), 'Saved file must start with full detail'
cases = []
for mode, playing, expected in [('AUTO',False,True),('AUTO',True,False),('AUTO',False,True),('DETAIL',True,True),('FAST',False,False)]:
    scene.earthstudio_preview_mode = mode
    assert helper.apply_mode(scene,playing) == expected
    bpy.context.view_layer.update()
    assert bool(control.path_resolve(path)) == expected
    assert main.hide_viewport == (not expected) and proxy.hide_viewport == expected
    assert not main.hide_render and proxy.hide_render
    cases.append(dict(mode=mode,playing=playing,full_detail=expected,render_11k_only=True))
(root/'reports/h9_11k_optimization/preview_mode_verification.json').write_text(json.dumps(cases,indent=2))
print('PREVIEW_MODES_VERIFIED',flush=True)
