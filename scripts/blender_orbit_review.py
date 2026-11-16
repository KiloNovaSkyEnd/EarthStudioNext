"""Create/render isolated real Blender orbit review, preserving prior exports."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import bpy
from mathutils import Vector, Quaternion

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ges.blender_orbit_atmosphere import RADIUS, install, sphere


def position(lon, lat, radius):
    lon, lat = map(math.radians, (lon, lat))
    return Vector((radius*math.cos(lat)*math.cos(lon), radius*math.cos(lat)*math.sin(lon), radius*math.sin(lat)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--frames', type=int, default=192)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--samples', type=int, default=24)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out = args.out.resolve()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    source = ROOT/config['source']
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    if args.frames < 5 or args.width < 320 or args.samples < 1:
        raise ValueError('Invalid review dimensions or sampling')
    args.out.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 12 if args.pilot else args.samples
    scene.cycles.use_denoising = True
    scene.cycles.volume_bounces = 2
    prefs = bpy.context.preferences.addons['cycles'].preferences
    try:
        prefs.compute_device_type = 'OPTIX'
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == 'OPTIX'
        if not any(d.use for d in prefs.devices):
            raise RuntimeError('No OPTIX GPU')
        scene.cycles.device = 'GPU'
    except Exception as error:
        print('GPU_FALLBACK', str(error), flush=True)
        scene.cycles.device = 'CPU'
    scene.render.resolution_x = 640 if args.pilot else args.width
    scene.render.resolution_y = round(scene.render.resolution_x*9/16)
    scene.render.resolution_percentage = 100
    scene.render.fps = 24
    scene.render.use_persistent_data = True
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.world = bpy.data.worlds.new('Space')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0, 0, 0, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = 0
    sun = Vector(config['sun_direction'])
    earth = sphere('Earth_observed_composite', RADIUS, 512, 256)
    earth['source_sha256'] = original
    mat = bpy.data.materials.new('Observed apparent RGB: no second Lambert lighting')
    mat.use_nodes = True
    if hasattr(mat.cycles, 'emission_sampling'):
        mat.cycles.emission_sampling = 'NONE'
    nodes = mat.node_tree.nodes
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    emission = nodes.new('ShaderNodeEmission')
    image = nodes.new('ShaderNodeTexImage')
    image.image = bpy.data.images.load(str(source), check_existing=False)
    image.image.pack()
    # Explicit geographic mapping avoids the default UV sphere's seam offset.
    geo = nodes.new('ShaderNodeNewGeometry')
    separate = nodes.new('ShaderNodeSeparateXYZ')
    mat.node_tree.links.new(geo.outputs['Position'], separate.inputs[0])
    from ges.blender_orbit_atmosphere import Graph
    graph = object.__new__(Graph)
    graph.nodes, graph.links = nodes, mat.node_tree.links
    lon = graph.op('ARCTAN2', separate.outputs['Y'], separate.outputs['X'])
    u = graph.op('ADD', graph.op('DIVIDE', lon, 2*math.pi), .5)
    v = graph.op('ADD', graph.op('DIVIDE', graph.op('ARCSINE', graph.op('DIVIDE', separate.outputs['Z'], RADIUS)), math.pi), .5)
    uv = nodes.new('ShaderNodeCombineXYZ')
    graph.connect(u, uv.inputs[0]); graph.connect(v, uv.inputs[1])
    graph.links.new(uv.outputs[0], image.inputs['Vector'])
    graph.links.new(image.outputs['Color'], emission.inputs['Color'])
    # A photographed apparent surface must not illuminate the atmosphere as a
    # giant emissive light. It is visible to camera rays, opaque black to Sun
    # shadow/secondary paths; atmosphere is lit by the real directional Sun.
    light_path = nodes.new('ShaderNodeLightPath')
    black = nodes.new('ShaderNodeBsdfDiffuse')
    black.inputs['Color'].default_value = (0,0,0,1)
    camera_surface = nodes.new('ShaderNodeMixShader')
    graph.links.new(light_path.outputs['Is Camera Ray'], camera_surface.inputs[0])
    graph.links.new(black.outputs[0], camera_surface.inputs[1])
    graph.links.new(emission.outputs[0], camera_surface.inputs[2])
    graph.links.new(camera_surface.outputs[0], output.inputs['Surface'])
    earth.data.materials.append(mat)
    atmosphere, glow = install(scene, sun)
    light = bpy.data.lights.new('UTC Sun', 'SUN')
    light.energy = 4.
    light.angle = math.radians(.53)
    obj = bpy.data.objects.new('UTC Sun', light)
    scene.collection.objects.link(obj)
    obj.rotation_euler = (-sun).to_track_quat('-Z', 'Y').to_euler()
    camera = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.clip_start = .5
    camera.data.clip_end = 150000
    camera.data.lens = 38.
    camera.data.sensor_width = 36.
    camera.rotation_mode = 'QUATERNION'
    scene.frame_start = 1
    scene.frame_end = args.frames
    # A continuous geographic path; dense keys avoid straight chords through Earth.
    waypoints = [(1,-75.,12.,30000.,-75.,8.,0.),(65,-65.,12.,7171.,-43.,12.,-90.),
                 (125,-10.,12.,16000.,10.,12.,0.),(185,55.,12.,16000.,75.,12.,0.),
                 (240,125.,12.,8500.,145.,12.,-90.)]
    def smooth(t):
        return t*t*(3-2*t)
    previous_rotation = None
    for frame in range(1, args.frames+1):
        path_time = 1+(frame-1)*239/(args.frames-1)
        a,b = next((a,b) for a,b in zip(waypoints,waypoints[1:]) if a[0] <= path_time <= b[0])
        t = smooth((path_time-a[0])/(b[0]-a[0]))
        vals = [x+(y-x)*t for x,y in zip(a[1:],b[1:])]
        lon,lat,r,tlon,tlat,roll = vals
        camera.location = position(lon,lat,r)
        rotation = (position(tlon,tlat,RADIUS)-camera.location).to_track_quat('-Z','Y')
        rotation = rotation @ Quaternion((0,0,1),math.radians(roll))
        if previous_rotation is not None:
            rotation.make_compatible(previous_rotation)
        camera.rotation_quaternion = rotation
        previous_rotation = rotation.copy()
        camera.keyframe_insert('location', frame=frame)
        camera.keyframe_insert('rotation_quaternion', frame=frame)
    scene['ES_source_utc'] = config['utc']
    scene['ES_sun_direction_ecef'] = list(sun)
    scene['ES_time_mode'] = 'Frozen observed weather and UTC; camera motion only. Not a weather timelapse.'
    scene['ES_limits'] = 'New Cycles volume candidate, not exact GLSL port; source is existing 8K composite, not native full-global detail.'
    scene.frame_set(round(args.frames*.52))
    scene.render.filepath = '//frames/frame_'
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.clip_start = .5
                area.spaces.active.clip_end = 150000
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
    notes = bpy.data.texts.new('READ_ME_验收说明')
    notes.write('Blender 大气与气辉运镜测试。天气和 UTC 固定，相机动画可自由修改。\n'
                'Scene Properties > Custom Properties: ES_atmosphere_gain / ES_airglow_gain，0关1开。\n'
                'F12 渲染当前帧。Z > Rendered 查看材质；空格播放相机关键帧并不保证实时渲染。\n'
                'Cycles GPU 需在 Preferences > System 启用 OptiX；也可改用 CPU。\n'
                '大气为 Cycles 体积候选，气辉为48点实际观察射线积分；不是当日大气观测。\n'
                '贴图已打包。未完成全球原生高分辨率、三维云或天气延时验收。\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out/'earth_orbit.blend'))
    report = dict(config=config, blender=bpy.app.version_string,
                  devices=[dict(name=d.name,type=d.type,use=d.use) for d in prefs.devices],
                  source_sha256=original, renders=[])
    frames = [1,round(args.frames*.27),round(args.frames*.52),round(args.frames*.77),args.frames] if args.pilot else range(1,args.frames+1)
    (args.out/'frames').mkdir()
    for frame in frames:
        scene.frame_set(frame)
        start = time.perf_counter()
        path = args.out/'frames'/f'frame_{frame:04d}.png'
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        report['renders'].append(dict(frame=frame, seconds=time.perf_counter()-start,
                                      camera=list(camera.location), altitude_km=camera.location.length-RADIUS))
        (args.out/'render_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('FRAME_READY', frame, report['renders'][-1]['seconds'], flush=True)
    assert original == hashlib.sha256(source.read_bytes()).hexdigest()


if __name__ == '__main__':
    main()
