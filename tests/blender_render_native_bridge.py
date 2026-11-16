"""Real GPU renders for editable takes, limb switches and native detail evidence."""
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from scripts.blender_support.native_disk_material import A, B

out = require_writable(sys.argv[sys.argv.index('--')+1])
out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
assert len([i for i in bpy.data.images if i.source == 'FILE']) == 16
assert all(i.filepath.startswith('//') and Path(bpy.path.abspath(i.filepath)).is_file() for i in bpy.data.images if i.source == 'FILE')
assert len([o for o in scene.objects if 'earthstudio_editable_camera' in o]) == 5
assert scene['earthstudio_native_shape'].to_list() == [22000, 22000]
scene.cycles.samples = 8
scene.cycles.adaptive_min_samples = 8
scene.render.resolution_x, scene.render.resolution_y = 960, 540
scene.render.resolution_percentage = 100
scene['blueAtmosphere'], scene['nightAirglow'] = False, False
records = []


def render(label):
    scene.render.filepath = str(out/(label+'.png'))
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    records.append(dict(name=label, camera=scene.camera.name, frame=scene.frame_current,
                        width=scene.render.resolution_x, height=scene.render.resolution_y,
                        matrix=[list(row) for row in scene.camera.matrix_world],
                        lens=scene.camera.data.lens, sensor_width=scene.camera.data.sensor_width,
                        blue=scene['blueAtmosphere'], warm=scene['nightAirglow']))
    (out/'render_records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print('NATIVE_RENDER_DONE', label, flush=True)


for identity, frame, label in [('A', 1, 'take_A_start'), ('A', 301, 'take_A_nadir'), ('A', 601, 'take_A_end'), ('B', 181, 'take_B_rotating')]:
    scene.camera = next(o for o in scene.objects if o.get('earthstudio_editable_camera') == identity)
    scene.frame_set(frame)
    render(label)

# Independent diagnostic camera; no change is saved back to the delivered blend.
data = bpy.data.cameras.new('Native full-disk diagnostic')
probe = bpy.data.objects.new(data.name, data)
scene.collection.objects.link(probe)
data.sensor_fit, data.sensor_width, data.lens = 'HORIZONTAL', 36, 36/(2*__import__('math').tan(__import__('math').radians(40)/2)*(960/540))
data.clip_start, data.clip_end = .00001, 1000
import math
target = Vector((A*math.cos(math.radians(140.7)), A*math.sin(math.radians(140.7)), 0))
probe.location = target.normalized()*(A+18)
probe.rotation_euler = (-probe.location).to_track_quat('-Z', 'Y').to_euler()
scene.camera = probe
for blue, warm, label in [(False, False, 'rim_00_off'), (True, False, 'rim_10_blue'), (False, True, 'rim_01_warm'), (True, True, 'rim_11_both'), (False, False, 'rim_00_return')]:
    scene['blueAtmosphere'], scene['nightAirglow'] = blue, warm
    render(label)

# Close native-detail view, with the same analytic texture material.
lon, lat = map(math.radians, (130.7, 18))
e2 = 1-(B/A)**2
normal = Vector((math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)))
n = A/math.sqrt(1-e2*math.sin(lat)**2)
target = Vector((n*math.cos(lat)*math.cos(lon), n*math.cos(lat)*math.sin(lon), n*(1-e2)*math.sin(lat)))
probe.location = target+normal*.6
probe.rotation_euler = (target-probe.location).to_track_quat('-Z', 'Y').to_euler()
scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
data.lens = 36/(2*math.tan(math.radians(40)/2)*(1920/1080))
render('native_detail_1080p')
print('PASS 10 real native material GPU renders; source blend preserved', flush=True)
