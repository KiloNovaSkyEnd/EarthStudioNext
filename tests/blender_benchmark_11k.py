"""Same camera/weather, EEVEE offscreen timings; not a live viewport FPS claim."""
import ctypes
import json
from pathlib import Path
import sys
import time

import bpy
from mathutils import Vector

root = Path(__file__).resolve().parents[1]
args = sys.argv[sys.argv.index('--') + 1:]
label = args[0]
out = root / 'reports/h9_11k_optimization'
out.mkdir(exist_ok=True)
target = out / (label + '.json')
if target.exists():
    raise FileExistsError('Prior benchmark preserved')
track = json.loads(Path('D:/Deepsky Software/Sentinel3_Studio_v0.1/test/all-take-cameras.json').read_text(encoding='utf-8'))['tracks'][0]
scene = next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track') == 'WEB_1')
bpy.context.window.scene = scene
control = bpy.data.objects[scene.camera['earthstudio_controller']]
paths = json.loads(control['earthstudio_parameter_paths'])
errors = dict(position_metres=0, direction=0)
for sample in track['samples']:
    scene.frame_set(round(1 + sample['seconds'] * 30))
    matrix = scene.camera.matrix_world
    errors['position_metres'] = max(errors['position_metres'], (matrix.translation - Vector(sample['position']) / 1e6).length * 1e6)
    errors['direction'] = max(errors['direction'], (-(matrix.to_3x3() @ Vector((0, 0, 1))) - Vector(sample['direction'])).length)
assert errors['position_metres'] < 20 and errors['direction'] < 2e-5
shell = next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
preview = len(args)>1 and args[1]=='preview'
if preview:
    shell.hide_render=True
    shell=next(o for o in scene.objects if o.get('earthstudio_preview_proxy'))
    shell.hide_render=False
tree = shell.data.materials[0].node_tree
textures = [n for n in tree.nodes if n.type == 'TEX_IMAGE']
assert all(Path(bpy.path.abspath(n.image.filepath)).is_file() for n in textures)
assert all(v.targets[0].id == control for d in tree.animation_data.drivers for v in d.driver.variables)

class Memory(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in
        ['peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'commit', 'peak_commit']]


def memory():
    value = Memory()
    value.cb = ctypes.sizeof(value)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.WinDLL('psapi').GetProcessMemoryInfo(ctypes.c_void_p(kernel.GetCurrentProcess()), ctypes.byref(value), value.cb)
    return dict(working_bytes=value.working, peak_working_bytes=value.peak_working, commit_bytes=value.commit)


scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.resolution_percentage = 100
if hasattr(scene.eevee, 'taa_render_samples'):
    scene.eevee.taa_render_samples = 8
scene.render.image_settings.file_format = 'PNG'
scene.render.use_simplify = False
if hasattr(scene.render, 'use_texture_cache'):
    scene.render.use_texture_cache = False
records = []
for index in [1, 37, 73, 73]:
    if len(records) < 3:
        for node in textures:
            node.image.buffers_free()
    frame = round(1 + (index - 1) / 72 * (scene.frame_end - 1))
    scene.frame_set(frame)
    selected = [round(frame + node.image_user.frame_offset) for node in textures]
    assert set(selected) == {index}, selected
    scene.render.filepath = str(out / f'{label}_{len(records)}.png')
    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    import gpu
    gpu.init()
    hardware = dict(renderer=gpu.platform.renderer_get(),vendor=gpu.platform.vendor_get(),maximum_texture=gpu.capabilities.max_texture_size_get())
    assert '4060' in hardware['renderer'],hardware
    record = dict(index=index, frame=frame, render_seconds=time.perf_counter() - started,
                  textures=len(textures), **memory())
    records.append(record)
    print('COMPACT_BENCHMARK', json.dumps(record), flush=True)
    target.write_text(json.dumps(dict(label=label, preview_only=preview, engine='BLENDER_EEVEE', resolution=[1280, 720],
        render_samples=getattr(scene.eevee, 'taa_render_samples', None), shader_nodes=len(tree.nodes),
        images=len(textures), hardware=hardware, actual_camera_samples_verified=len(track['samples']), errors=errors, records=records,
        scope='Offscreen rendering, first3 freed image buffers then repeat last. Shared OS disk/GPU shader caches and background conversion may affect timings. Not live playback FPS.'), indent=2), encoding='utf-8')
print('COMPACT_BENCHMARK_COMPLETE', label, flush=True)
