"""No stochastic atmosphere closures, persistent independent controls and model bounds."""
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.layered_atmosphere import blue_weight
from ges_next.isolation import require_writable

assert len([i for i in bpy.data.images if i.source == 'FILE']) == 16
records = []
for scene in bpy.data.scenes:
    proxies = [o for o in scene.objects if o.get('earthstudio_layered_atmosphere')]
    assert len(proxies) == 1
    proxy = proxies[0]
    material = proxy.data.materials[0]
    types = [n.bl_idname for n in material.node_tree.nodes]
    assert 'ShaderNodeBsdfTransparent' not in types and 'ShaderNodeMixShader' not in types
    assert 'ShaderNodeVolumeScatter' not in types and 'ShaderNodeVolumePrincipled' not in types
    assert types.count('ShaderNodeTexImage') == 16 and types.count('ShaderNodeEmission') == 1
    assert all(o.hide_render and o.hide_viewport for o in scene.objects if o.name.startswith(('WGS84 Earth', '大气显示')))
    control = bpy.data.objects[scene.camera['earthstudio_controller']]
    paths = json.loads(control['earthstudio_parameter_paths'])
    assert control.path_resolve(paths['["blueDensity"]']) == 1
    assert control.path_resolve(paths['["blueThickness"]']) == 1
    for curve in material.node_tree.animation_data.drivers:
        for variable in curve.driver.variables:
            assert variable.targets[0].id == control
    records.append(dict(scene=scene.name, opaque_analytic_proxy=True, independent_control=control.name))
assert len(records) == 5
assert blue_weight(0, 1, inside=True) == 0
assert .35 < blue_weight(0, 0, inside=True) < .4
assert .5 < blue_weight(0, 0) < .6
assert blue_weight(0, .5, inside=True) < .02
assert blue_weight(0, .1, inside=True) > blue_weight(0, .5, inside=True)
assert blue_weight(20, 0, density=1.4) > blue_weight(20, 0)
assert blue_weight(20, 0, thickness=1.4) > blue_weight(20, 0)
assert blue_weight(0, .2, inside=True, thickness=1.4) > blue_weight(0, .2, inside=True)
for h in range(0, 200):
    assert blue_weight(h, 0) >= blue_weight(h+1, 0)
    assert blue_weight(h, 0, density=0) == 0
report = dict(scenes=records, all_native_images=16, no_transparent_or_volume_closure=True,
              nadir_haze_weight=blue_weight(0, 1, inside=True),
              inside_horizon_weight=blue_weight(0, 0, inside=True), outside_horizon_weight=blue_weight(0, 0),
              adjustable_density_thickness=True, display_model_not_retrieval=True)
require_writable(sys.argv[sys.argv.index('--')+1]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS layered display nodes, independent controls, no stochastic opacity, bounded profile', flush=True)
