"""100km camera inside render proxy, unobserved hemisphere, and reference-angle view."""
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from scripts.blender_support.native_disk_material import A, B

out = require_writable(sys.argv[sys.argv.index('--')+1])
out.mkdir(parents=True, exist_ok=True)
scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'A')
bpy.context.window.scene = scene
control = bpy.data.objects[scene.camera['earthstudio_controller']]
paths = json.loads(control['earthstudio_parameter_paths'])
for name in ('blueAtmosphere', 'nightAirglow'):
    owner, attr = paths['["'+name+'"]'].rsplit('.', 1)
    setattr(control.path_resolve(owner), attr, False)
control.update_tag()
data = bpy.data.cameras.new('Atmosphere diagnostic')
camera = bpy.data.objects.new(data.name, data)
scene.collection.objects.link(camera)
scene.camera = camera
scene.render.resolution_x, scene.render.resolution_y = 640, 360
scene.render.resolution_percentage = 100
scene.cycles.samples, scene.cycles.adaptive_min_samples = 16, 16
scene.render.use_persistent_data = True
data.sensor_fit, data.sensor_width = 'HORIZONTAL', 36
data.lens = 36/(2*math.tan(math.radians(40)/2)*(640/360))
data.clip_start, data.clip_end = .00001, 1000


def point(lon, lat, height):
    lon, lat = map(math.radians, (lon, lat))
    e2 = 1-(B/A)**2
    n = A/math.sqrt(1-e2*math.sin(lat)**2)
    return Vector(((n+height)*math.cos(lat)*math.cos(lon), (n+height)*math.cos(lat)*math.sin(lon), (n*(1-e2)+height)*math.sin(lat)))


def render(name, location, target, roll=0):
    camera.location = location
    camera.rotation_euler = (target-location).to_track_quat('-Z', 'Y').to_euler()
    camera.rotation_euler.rotate_axis('Z', math.radians(roll))
    scene.render.filepath = str(out/(name+'.png'))
    bpy.ops.render.render(write_still=True)
    print('PROBE_DONE', name, flush=True)


render('camera_inside_proxy_100km', point(130.7, 18, .1), point(130.7, 18, 0))
render('unobserved_hemisphere', point(-39.3, 0, 18), Vector((0, 0, 0)))
owner, attr = paths['["blueAtmosphere"]'].rsplit('.', 1)
setattr(control.path_resolve(owner), attr, True)
control.update_tag()
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
render('reference_angle', point(115, 20, 1.6), point(140, 15, 0), 30)
