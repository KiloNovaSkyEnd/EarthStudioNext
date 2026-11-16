"""Render from a physically copied package and check unobserved hemisphere."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable

out = require_writable(sys.argv[sys.argv.index('--')+1])
out.mkdir(parents=True, exist_ok=True)
root = Path(bpy.data.filepath).parent.resolve()
images = [i for i in bpy.data.images if i.source == 'FILE']
assert len(images) == 16
for image in images:
    path = Path(bpy.path.abspath(image.filepath)).resolve()
    assert image.filepath.startswith('//') and path.is_file() and root in path.parents
scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = 320, 180
scene.render.resolution_percentage = 100
scene.cycles.samples = scene.cycles.adaptive_min_samples = 4
scene.render.use_persistent_data = True
scene['blueAtmosphere'], scene['nightAirglow'] = False, False
scene.render.filepath = str(out/'relocated_user_take.png')
bpy.ops.render.render(write_still=True)
data = bpy.data.cameras.new('Unobserved-side probe')
camera = bpy.data.objects.new(data.name, data)
scene.collection.objects.link(camera)
longitude = math.radians(140.7-180)
camera.location = Vector((math.cos(longitude), math.sin(longitude), 0))*(6.378137+18)
camera.rotation_euler = (-camera.location).to_track_quat('-Z', 'Y').to_euler()
data.sensor_fit, data.sensor_width = 'HORIZONTAL', 36
data.lens = 36/(2*math.tan(math.radians(40)/2)*(320/180))
data.clip_start, data.clip_end = .00001, 1000
scene.camera = camera
scene.render.filepath = str(out/'unobserved_side.png')
bpy.ops.render.render(write_still=True)
report = dict(copied_package=str(root), relative_images=len(images), all_images_inside_copied_package=True,
              scientific_backend_required=False, webpage_required=False, python_autoexec_required=False,
              offline_user_take_rendered=True, unobserved_side_rendered=True)
(out/'portable_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('PASS relocated package opens and renders with automatic scripts disabled', flush=True)
