"""Bounded actual EEVEE renders with independent ground and atmosphere toggles."""
import json
from pathlib import Path
import bpy

package=Path(bpy.data.filepath).parent
scene=bpy.context.scene
control=bpy.data.objects[scene.camera['earthstudio_controller']]
paths=json.loads(control['earthstudio_parameter_paths'])
scene.render.engine='CYCLES'
scene.cycles.samples=8;scene.cycles.use_denoising=True
preferences=bpy.context.preferences.addons['cycles'].preferences
try:
    preferences.compute_device_type='OPTIX';preferences.get_devices()
    for device in preferences.devices: device.use=device.type!='CPU'
    scene.cycles.device='GPU'
except Exception:
    scene.cycles.device='CPU'
scene.render.resolution_x=960;scene.render.resolution_y=540
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
folder=package/'verification';folder.mkdir(exist_ok=True)
def atmosphere(key,value):
    path=paths['["'+key+'"]'];owner,attribute=path.rsplit('.',1)
    setattr(control.path_resolve(owner),attribute,value)
records=[]
for name,ground,blue,warm,hue,saturation in [
    ('ground_off',0,0,0,0,1),('ground_on',1,0,0,0,1),
    ('ground_tinted',1,0,0,80,1.8),('blue_only',1,1,0,0,1),
    ('warm_only',1,0,1,0,1),('both',1,1,1,0,1)]:
    atmosphere('groundEnabled',bool(ground));atmosphere('groundHue',hue);atmosphere('groundSaturation',saturation)
    atmosphere('blueAtmosphere',bool(blue));atmosphere('nightAirglow',bool(warm))
    control.update_tag();scene.frame_set(1);bpy.context.view_layer.update()
    scene.render.filepath=str(folder/(name+'.png'))
    bpy.ops.render.render(write_still=True)
    records.append(dict(name=name,ground=ground,blue=blue,warm=warm,hue=hue,saturation=saturation))
from math import radians,cos,sin
from mathutils import Vector
camera=bpy.data.objects.new('QA day-limb camera',bpy.data.cameras.new('QA day-limb lens'))
scene.collection.objects.link(camera);scene.camera=camera
camera.location=Vector((17*cos(radians(20))*cos(radians(60)),17*cos(radians(20))*sin(radians(60)),17*sin(radians(20))))
camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.lens=35;camera.data.clip_end=1000
for name,enabled in [('day_limb_blue_off',False),('day_limb_blue_on',True)]:
    atmosphere('blueAtmosphere',enabled);atmosphere('nightAirglow',False)
    control.update_tag();bpy.context.view_layer.update()
    scene.render.filepath=str(folder/(name+'.png'));bpy.ops.render.render(write_still=True)
    records.append(dict(name=name,blue=enabled,qa_camera_only=True))
(folder/'render_cases.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
