"""Reopen delivered scene and render independent feature ablations."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import bpy
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--stills', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    args.out = args.out.resolve()
    args.out.mkdir(exist_ok=False)
    scene = bpy.context.scene
    earth = bpy.data.objects['Earth_observed_composite']
    atmosphere = bpy.data.objects['Atmosphere_volume']
    glow = bpy.data.objects.get('Airglow_ray_integral_shell') or bpy.data.objects.get('Airglow_volume')
    texture = next(n.image for n in earth.data.materials[0].node_tree.nodes if n.type == 'TEX_IMAGE')
    assert texture.packed_file is not None
    assert hashlib.sha256(texture.packed_file.data).hexdigest() == earth['source_sha256']
    assert scene['ES_source_utc'] == '2020-10-29T16:40:00Z'
    assert scene.camera.rotation_mode == 'QUATERNION'
    assert all(not obj.animation_data for obj in (earth,atmosphere,glow,bpy.data.objects['UTC Sun']))
    poses = []
    previous = None
    angles = []
    for frame in range(scene.frame_start, scene.frame_end+1):
        scene.frame_set(frame)
        camera = scene.camera
        altitude = camera.location.length-6371.
        assert altitude > 799.9
        rotation = camera.rotation_quaternion.copy()
        if previous is not None:
            angles.append(float(previous.rotation_difference(rotation).angle*180/np.pi))
        previous = rotation
        poses.append(dict(frame=frame,position=list(camera.location),altitude_km=altitude))
    assert max(angles)<8.,max(angles)
    scene.cycles.samples = 32
    scene.cycles.seed = 0
    scene.cycles.use_animated_seed = False
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'
    prefs.get_devices()
    for device in prefs.devices:
        device.use = device.type == 'OPTIX'
    scene.cycles.device = 'GPU'
    report = dict(packed_texture_sha256=earth['source_sha256'],all_camera_altitudes_safe=True,
                  max_frame_rotation_degrees=max(angles),camera_poses=poses,
                  geometry_and_sun_not_camera_parented=True,feature_renders=[])
    def render(label, frame, atmo, airglow, hidden=False):
        scene['ES_atmosphere_gain'] = float(atmo)
        scene['ES_airglow_gain'] = float(airglow)
        atmosphere.hide_render = glow.hide_render = hidden
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        path = args.out/f'{label}_{frame:04d}.png'
        scene.render.filepath = str(path)
        start = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path),check_existing=False)
        values = np.empty(image.size[0]*image.size[1]*4,np.float32)
        image.pixels.foreach_get(values)
        values = values.reshape(image.size[1],image.size[0],4)[...,:3].copy()
        bpy.data.images.remove(image)
        report['feature_renders'].append(dict(file=path.name,seconds=time.perf_counter()-start))
        return values
    for frame in (1,round(scene.frame_end*.52),scene.frame_end):
        full = render('full',frame,1,1)
        without_glow = render('no_airglow',frame,1,0)
        without_all = render('no_atmosphere',frame,0,0)
        report.setdefault('effect_deltas',[]).append(dict(frame=frame,
            atmosphere_max_encoded=float(np.abs(without_glow-without_all).max()),
            atmosphere_mean_encoded=float(np.abs(without_glow-without_all).mean()),
            airglow_max_encoded=float(np.abs(full-without_glow).max()),
            airglow_mean_encoded=float(np.abs(full-without_glow).mean())))
        if frame == scene.frame_end:
            hidden = render('hidden_reference',frame,0,0,True)
            error = float(np.abs(hidden-without_all).max())
            assert error<=.004,error
            report['both_off_vs_hidden_max_linear'] = error
            atmosphere.hide_render = glow.hide_render = False
            glow_only = render('airglow_only',frame,0,1)
            weather_emission = next(n for n in earth.data.materials[0].node_tree.nodes if n.type=='EMISSION')
            weather_emission.inputs['Strength'].default_value = 0.
            isolated = render('isolated_airglow_black_earth',frame,0,1)
            weather_emission.inputs['Strength'].default_value = 1.
            # Independent CPU ray/sphere geometry. Image pixels are bottom-up.
            height,width = glow_only.shape[:2]
            corners = scene.camera.data.view_frame(scene=scene)
            hx = max(abs(p.x/p.z) for p in corners)
            hy = max(abs(p.y/p.z) for p in corners)
            y,x = np.mgrid[:height,:width]
            rays = np.stack([((x+.5)/width*2-1)*hx,((y+.5)/height*2-1)*hy,-np.ones_like(x)],axis=-1)
            rays = rays@np.array(scene.camera.matrix_world.to_3x3()).T
            rays /= np.linalg.norm(rays,axis=-1,keepdims=True)
            origin = np.array(scene.camera.location)
            along = np.sum(rays*origin,axis=-1)
            closest = origin-along[...,None]*rays
            impact = np.linalg.norm(closest,axis=-1)
            interior = (impact<6371.-50)&(along<0)
            # Black opaque Earth isolates the effect from texture antialiasing
            # sample changes between render passes. It is a synthetic diagnostic.
            interior_error = float(abs(isolated)[interior].max())
            assert interior_error<1.1/255,interior_error
            report['airglow_opaque_interior_max_dn'] = interior_error*255
            report['weather_pass_difference_interior_mean_dn'] = float(abs(glow_only-without_all)[interior].mean()*255)
            selected = (impact>6371.+20)&(impact<6371.+125)&(along<0)
            indices = np.flatnonzero(selected.ravel())[::max(1,int(selected.sum()/200))]
            b = impact.ravel()[indices]
            p = closest.reshape(-1,3)[indices]
            ray = rays.reshape(-1,3)[indices]
            half = np.sqrt((6371.+130)**2-b*b)
            t = half[:,None]*(-1+(np.arange(4096)+.5)*2/4096)
            points = p[:,None,:]+t[...,None]*ray[:,None,:]
            radius = np.linalg.norm(points,axis=-1)
            sun = np.array(scene['ES_sun_direction_ecef'])
            solar = np.sum(points*sun,axis=-1)/radius
            u = np.clip((solar+.309017)/(.309017-.104528),0,1)
            night = 1-u**3*(u*(u*6-15)+10)
            column = (np.exp(-.5*((radius-6371.-90)/7)**2)*night).sum(axis=1)*2*half/4096*.000003
            expected = column[:,None]*np.array([.8,.38,.10])
            expected = np.where(expected<=.0031308,expected*12.92,1.055*np.maximum(expected,0)**(1/2.4)-.055)
            actual = isolated.reshape(-1,3)[indices]
            error_dn = abs(actual-expected)*255
            report['airglow_cpu_4096_reference'] = dict(pixels=len(indices),mean_dn=float(error_dn.mean()),max_dn=float(error_dn.max()))
            assert error_dn.mean()<2.,report['airglow_cpu_4096_reference']
    scene['ES_atmosphere_gain'] = scene['ES_airglow_gain'] = 1.
    atmosphere.hide_render = glow.hide_render = False
    assert report['effect_deltas'][0]['atmosphere_max_encoded'] > .005
    assert report['effect_deltas'][-1]['airglow_max_encoded'] > .0001
    if args.stills:
        scene.render.resolution_x = 3840
        scene.render.resolution_y = 2160
        scene.cycles.samples = 48
        for frame in (round(scene.frame_end*.27),scene.frame_end):
            render('4k_full',frame,1,1)
        report['four_k_actual_renders'] = True
        # A separately created, non-animated camera proves there is no camera
        # image dependency. The shipped main scene itself stays unchanged.
        import math
        from mathutils import Vector, Quaternion
        original_camera = scene.camera
        camera = original_camera.copy()
        camera.data = original_camera.data.copy()
        camera.animation_data_clear()
        scene.collection.objects.link(camera)
        lon,lat = map(math.radians,(-60.,15.))
        camera.location = Vector((math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)))*(6371+1000)
        lon = math.radians(-38.)
        target = Vector((math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)))*6371
        camera.rotation_quaternion = (target-camera.location).to_track_quat('-Z','Y') @ Quaternion((0,0,1),-math.pi/2)
        camera.data.lens = 50.
        scene.camera = camera
        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1080
        render('independent_free_camera',round(scene.frame_end*.27),1,1)
        scene.camera = original_camera
        report['independent_camera_actual_render'] = True
    report['passed'] = True
    (args.out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('VERIFIED_ORBIT',json.dumps(report['effect_deltas']),flush=True)


if __name__ == '__main__':
    main()
