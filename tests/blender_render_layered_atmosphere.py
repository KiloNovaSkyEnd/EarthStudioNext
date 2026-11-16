"""Matched-camera old/new atmosphere renders, independent switches and close detail."""
import argparse
import json
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path)
parser.add_argument('--old', action='store_true')
parser.add_argument('--one-sample', action='store_true')
parser.add_argument('--eevee', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
out = require_writable(args.output)
out.mkdir(parents=True, exist_ok=True)
scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'A')
bpy.context.window.scene = scene
control = bpy.data.objects[scene.camera['earthstudio_controller']]
paths = json.loads(control['earthstudio_parameter_paths'])
scene.frame_set(1)
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.resolution_percentage = 100
scene.cycles.samples = 64
scene.cycles.adaptive_min_samples = 16
scene.render.use_persistent_data = True
scene.cycles.use_denoising = False
records = []


def set_value(name, value):
    owner, attribute = paths['["'+name+'"]'].rsplit('.', 1)
    setattr(control.path_resolve(owner), attribute, value)
    control.update_tag()
    bpy.context.view_layer.update()


def render(label):
    scene.render.filepath = str(out/(label+'.png'))
    bpy.ops.render.render(write_still=True)
    records.append(dict(name=label, width=scene.render.resolution_x, height=scene.render.resolution_y,
                        matrix=[list(row) for row in scene.camera.matrix_world], frame=scene.frame_current,
                        lens=scene.camera.data.lens, sensor_width=scene.camera.data.sensor_width))
    name = ('old' if args.old else 'new')+('_eevee_noise' if args.eevee and args.one_sample else '_eevee' if args.eevee else '_noise' if args.one_sample else '')+'_records.json'
    (out/name).write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('ATMOSPHERE_COMPARISON_DONE', label, flush=True)


if args.eevee:
    scene.render.engine = 'BLENDER_EEVEE'
    set_value('blueAtmosphere', True)
    set_value('nightAirglow', False)
    scene.eevee.taa_render_samples = 1 if args.one_sample else 64
    prefix = 'old' if args.old else 'new'
    render(prefix+'_blue_eevee'+('_1spp' if args.one_sample else ''))
    if args.old and not args.one_sample:
        scene.eevee.taa_render_samples = 1
        render('old_blue_eevee_1spp')
    sys.exit(0)
if args.one_sample:
    scene.cycles.samples = 1
    scene.cycles.use_adaptive_sampling = False
    set_value('blueAtmosphere', True)
    set_value('nightAirglow', False)
    render('old_blue_1spp' if args.old else 'new_blue_1spp')
    sys.exit(0)
set_value('blueAtmosphere', False)
set_value('nightAirglow', False)
render('old_off' if args.old else 'new_off')
set_value('blueAtmosphere', True)
render('old_blue' if args.old else 'new_blue')
if not args.old:
    set_value('blueDensity', 1.4)
    set_value('blueThickness', 1.2)
    render('new_richer')
    set_value('blueDensity', 1.)
    set_value('blueThickness', 1.)
    set_value('nightAirglow', True)
    render('new_both')
    set_value('blueAtmosphere', False)
    render('new_warm')
    set_value('nightAirglow', False)
    render('new_off_return')
    # Overhead view must preserve native cloud detail, not wash the whole disk blue.
    scene.frame_set(301)
    set_value('blueAtmosphere', False)
    render('nadir_off')
    set_value('blueAtmosphere', True)
    render('nadir_blue')
    # Reuse the validated native-detail camera from prior verification geometry.
    import math
    from mathutils import Vector
    from scripts.blender_support.native_disk_material import A, B
    data = bpy.data.cameras.new('Native detail verification')
    camera = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(camera)
    lon, lat = map(math.radians, (130.7, 18))
    e2 = 1-(B/A)**2
    n = A/math.sqrt(1-e2*math.sin(lat)**2)
    target = Vector((n*math.cos(lat)*math.cos(lon), n*math.cos(lat)*math.sin(lon), n*(1-e2)*math.sin(lat)))
    normal = Vector((math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)))
    camera.location = target+normal*.6
    camera.rotation_euler = (target-camera.location).to_track_quat('-Z', 'Y').to_euler()
    data.sensor_fit, data.sensor_width = 'HORIZONTAL', 36
    data.lens = 36/(2*math.tan(math.radians(40)/2)*(1920/1080))
    data.clip_start, data.clip_end = .00001, 1000
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    set_value('blueAtmosphere', False)
    render('native_detail_off')
