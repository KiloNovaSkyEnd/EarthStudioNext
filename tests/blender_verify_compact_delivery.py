"""Verify final11K asset selection, actual user motion, preview/render isolation."""
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

root = Path(__file__).resolve().parents[1]
track = json.loads(Path('D:/Deepsky Software/Sentinel3_Studio_v0.1/test/all-take-cameras.json').read_text(encoding='utf-8'))['tracks'][0]
scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'WEB_1')
bpy.context.window.scene = scene
control = bpy.data.objects[scene.camera['earthstudio_controller']]
paths = json.loads(control['earthstudio_parameter_paths'])
main = next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
proxy = next(o for o in scene.objects if o.get('earthstudio_preview_proxy'))
high = next(n for n in main.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE')
movie = next(n for n in proxy.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE')
assert high.image.source == 'SEQUENCE' and movie.image.source == 'MOVIE'
probe = bpy.data.images.load(bpy.path.abspath(high.image.filepath), check_existing=False)
assert list(probe.size) == [11000, 11000]
bpy.data.images.remove(probe)
assert list(movie.image.size) == [4096, 2048]
assert all(Path(bpy.path.abspath(n.image.filepath)).is_file() for n in [high, movie])
assert not main.hide_render and proxy.hide_render
seen, errors = set(), dict(position_metres=0, direction=0, up=0)
original_camera=json.loads((root/'reports/h9_11k_optimization/original_saved_camera.json').read_text())
matrix_difference=0
checks=[]
for sample in track['samples']:
    frame = round(1 + sample['seconds'] * 30)
    scene.frame_set(frame)
    nominal = min(73, 1 + math.floor(sample['seconds'] / track['samples'][-1]['seconds'] * 72 + 1e-5))
    expected = 10 if nominal == 11 else nominal
    actual = [round(frame + n.image_user.frame_offset) for n in [high, movie]]
    assert actual == [expected, expected], (frame, nominal, actual)
    seen.add(nominal)
    matrix = scene.camera.matrix_world
    baseline=original_camera[frame-1]['matrix']
    matrix_difference=max(matrix_difference,max(abs(matrix[i][j]-baseline[i][j]) for i in range(4) for j in range(4)))
    errors['position_metres'] = max(errors['position_metres'], (matrix.translation - Vector(sample['position']) / 1e6).length * 1e6)
    errors['direction'] = max(errors['direction'], (-(matrix.to_3x3() @ Vector((0, 0, 1))) - Vector(sample['direction'])).length)
    errors['up'] = max(errors['up'], ((matrix.to_3x3() @ Vector((0, 1, 0))) - Vector(sample['up'])).length)
assert len(seen) == 73 and matrix_difference < 2e-7,dict(nodes=len(seen),errors=errors,matrix_difference_from_original_saved_blender=matrix_difference)
owner, attribute = paths['["previewHigh"]'].rsplit('.', 1)
switch = control.path_resolve(owner)
for enabled in [False, True, False]:
    setattr(switch, attribute, enabled)
    control.update_tag()
    scene.frame_set(1)
    bpy.context.view_layer.update()
    assert main.hide_viewport == (not enabled) and proxy.hide_viewport == enabled,dict(enabled=enabled,main=main.hide_viewport,proxy=proxy.hide_viewport,control_value=control.path_resolve(paths['["previewHigh"]']),main_driver_valid=[d.is_valid for d in main.animation_data.drivers],proxy_driver_valid=[d.is_valid for d in proxy.animation_data.drivers])
    assert not main.hide_render and proxy.hide_render
    checks.append(dict(high_detail_preview=enabled, final_11k_render=True, preview_excluded_from_render=True))
for obj in [main, proxy]:
    for driver in obj.data.materials[0].node_tree.animation_data.drivers:
        assert driver.is_valid
        assert all(variable.targets[0].id == control for variable in driver.driver.variables)
    assert all(d.is_valid for d in obj.animation_data.drivers)
template = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'USER')
template_control = bpy.data.objects[template.camera['earthstudio_controller']]
assert template_control != control
for key in ['blueAtmosphere', 'nightAirglow', 'blueDensity', 'blueThickness', 'blueHue', 'blueSaturation', 'blueBrightness', 'warmDensity', 'warmThickness', 'warmHue', 'warmSaturation', 'warmBrightness']:
    assert paths['["'+key+'"]']
report = dict(user_export_samples=len(track['samples']), all73_weather_nodes_verified=True,
              preview_and_render_match_weather=True, missing_actual_observation_preserved=True,
              single_11k_render_texture=True, movie_is_preview_only=True,
              viewport_detail_toggle=checks, atmosphere_controls_preserved=True,
              separate_controller_ownership=True, errors_from_web_export=errors,
              maximum_matrix_difference_from_original_saved_blender=matrix_difference,
              saved_file=bpy.data.filepath)
(root / 'reports/h9_11k_optimization/delivery_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('COMPACT_DELIVERY_VERIFIED', json.dumps(report), flush=True)
