"""Explicit OptiX device selection, shared by saved scenes and batch rendering."""
import bpy


def configure(scene):
    preferences=bpy.context.preferences.addons['cycles'].preferences
    preferences.compute_device_type='OPTIX'
    preferences.get_devices()
    selected=[]
    for device in preferences.devices:
        device.use=device.type=='OPTIX'
        if device.use: selected.append(device.name)
    if not selected:
        raise RuntimeError('No OptiX device available; CPU fallback must be explicit')
    scene.render.engine='CYCLES'; scene.cycles.device='GPU'
    scene.cycles.samples=64
    scene.cycles.use_adaptive_sampling=True
    scene.cycles.adaptive_min_samples=16
    scene.cycles.adaptive_threshold=.01
    # Keep real weather texture detail; do not denoise the satellite surface.
    scene.cycles.use_denoising=False
    scene['earth_render_backend']='OPTIX'
    scene['earth_render_devices']=', '.join(selected)
    print('EARTH_GPU_RENDER',selected,flush=True)
    return selected
