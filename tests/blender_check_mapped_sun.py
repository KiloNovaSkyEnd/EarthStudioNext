"""Solar node UTC/data/driver consistency, not an independent ephemeris accuracy claim."""
import bpy,json,sys,math
from pathlib import Path
from datetime import datetime
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
source=root/'reports/project_source_clock/built_sequence/sequence_manifest.json'
manifest=json.loads(source.read_text(encoding='utf-8'));vectors=manifest['suns'];error=0
reference=json.loads((root/'reports/m14_editing/solar_reference.json').read_text())
for node,vector in zip(manifest['nodes'],vectors):
    expected=reference[node['utc']]
    error=max(error,max(abs(float(a)-float(b)) for a,b in zip(expected,vector)))
assert error<1e-12
rows=[]
for scene in bpy.data.scenes:
    if not scene.get('earthstudio_weather_clock_mode'):continue
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    formal=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere') and not o.get('earthstudio_preview_proxy'))
    tree=formal.data.materials[0].node_tree
    clock=next(n for n in tree.nodes if n.label=='天气时间 UTC−7')
    driver=next(c.driver for c in tree.animation_data.drivers if c.data_path==clock.outputs[0].path_from_id('default_value'))
    target=driver.variables[0].targets[0]
    assert target.id==control and target.data_path==path
    curves=sorted([n for n in tree.nodes if n.label.startswith('UTC太阳方向 ')],key=lambda n:n.label)
    assert len(curves)==3
    max_error=0
    for axis,curve in enumerate(curves):
        points=curve.mapping.curves[0].points
        assert len(points)==len(vectors)
        for point,vector in zip(points,vectors):max_error=max(max_error,abs(point.location.y-vector[axis]))
    assert max_error<1e-6
    rows.append(dict(scene=scene.name,clock_driver_matches=True,solar_vector_node_error=max_error))
assert len(rows)==3
(root/'reports/m14_editing/solar_clock.json').write_text(json.dumps(dict(passed=True,ephemeris_data_error=error,rows=rows,independent_ephemeris_accuracy_claim=False),ensure_ascii=False,indent=2),encoding='utf-8')
print('MAPPED_SOLAR_UTC_AND_DRIVER_CONSISTENCY_PASSED',flush=True)
