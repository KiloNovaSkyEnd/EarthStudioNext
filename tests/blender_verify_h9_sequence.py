"""Fresh no-autoexec native weather clock/scene independence and actual renders."""
import json,sys,math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.editable_camera import curves
from scripts.blender_support.gpu import configure
out=Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(parents=True,exist_ok=True)
root=Path(bpy.data.filepath).parent
report={'scenes':[],'renders':[]}
assert len(bpy.data.scenes) in (5,6)
images=[i for i in bpy.data.images if i.source=='SEQUENCE']
assert len(images)==16
for image in images:
    assert image.filepath.startswith('//')
    assert Path(bpy.path.abspath(image.filepath)).is_relative_to(root)
    assert Path(bpy.path.abspath(image.filepath)).is_file()
actions=set()
for scene in bpy.data.scenes:
    bpy.context.window.scene=scene
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    actions.add(control.animation_data.action.as_pointer())
    paths=json.loads(control['earthstudio_parameter_paths']);path=paths['["weatherHours"]']
    shells=[o for o in scene.objects if o.get('earthstudio_layered_atmosphere')]
    assert len(shells)==1,(scene.name,len(shells))
    obj=shells[0]
    tree=obj.data.materials[0].node_tree
    textures=[n for n in tree.nodes if n.bl_idname=='ShaderNodeTexImage'];assert len(textures)==16
    assert all(v.targets[0].id==control for d in tree.animation_data.drivers for v in d.driver.variables)
    assert sum(n.bl_idname=='ShaderNodeHueSaturation' for n in tree.nodes)==2
    assert sum(n.bl_idname=='ShaderNodeFloatCurve' for n in tree.nodes)==3
    for index in range(73):
        frame=scene.frame_start+index/72*(scene.frame_end-scene.frame_start)
        scene.frame_set(math.floor(frame),subframe=frame%1)
        hours=control.path_resolve(path)
        expected=min(73,max(1,math.floor((hours-6)*6+1.00001)))
        assert expected==index+1,(scene.name,index,hours)
        for texture in textures:
            actual=texture.image_user.frame_offset+scene.frame_current
            assert actual==expected,(scene.name,index,actual,expected)
    scene.frame_set(scene.frame_start)
    report['scenes'].append(dict(name=scene.name,nodes_verified=73,texture_drivers=16))
assert len(actions)==len(bpy.data.scenes)
report['independent_actions']=True
(out/'structure.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('STRUCTURE_VERIFIED_CLOCK_NODES',len(report['scenes'])*73,flush=True)

scene=list(bpy.data.scenes)[2];bpy.context.window.scene=scene;scene.frame_set(1)
control=bpy.data.objects[scene.camera['earthstudio_controller']];paths=json.loads(control['earthstudio_parameter_paths'])
weather_path=paths['["weatherHours"]']
for curve in curves(control):
    if curve.data_path==weather_path:curve.mute=True
def set_value(key,value):
    owner,attribute=paths['["'+key+'"]'].rsplit('.',1)
    setattr(control.path_resolve(owner),attribute,value);control.update_tag();bpy.context.view_layer.update()
camera=bpy.data.objects.new('独立验收相机',bpy.data.cameras.new('独立验收相机'))
scene.collection.objects.link(camera);camera.matrix_world=scene.camera.matrix_world.copy();camera.data.lens=scene.camera.data.lens
camera.data.clip_start=.00001;camera.data.clip_end=1000;scene.camera=camera
configure(scene);scene.cycles.samples=4;scene.cycles.adaptive_min_samples=4
scene.render.resolution_x,scene.render.resolution_y=640,360;scene.render.resolution_percentage=100
scene.render.use_persistent_data=False
set_value('blueAtmosphere',False);set_value('nightAirglow',False)
for hour,name in [(6,'weather_start'),(12,'weather_middle'),(18,'weather_end'),(7+40/60,'missing_0740')]:
    set_value('weatherHours',hour)
    path=out/(name+'.png');scene.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)
    im=bpy.data.images.load(str(path),check_existing=False);pixels=np.array(im.pixels[:]).reshape((-1,4))[:,:3]
    foreground=pixels[pixels.max(axis=1)>.02]
    report['renders'].append(dict(name=name,hour=hour,mean=pixels.mean(axis=0).tolist(),std=pixels.std(axis=0).tolist(),
        foreground_std=foreground.std(axis=0).tolist()))
    bpy.data.images.remove(im)
    print('WEATHER_RENDERED',name,flush=True)
assert max(report['renders'][-1]['foreground_std'])<.003,'Missing observed surface must be neutral; background space is black'
assert np.linalg.norm(np.array(report['renders'][0]['mean'])-report['renders'][2]['mean'])>.02
set_value('weatherHours',18);set_value('blueAtmosphere',True);set_value('nightAirglow',True)
camera.location=Vector((0,0,0)) # Replace both angle and roll, independent of delivered rigs.
lon,lat=map(math.radians,(125,20));point=Vector((math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat)))
camera.location=point*10.9;target=point*6.37
camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler();camera.rotation_euler.rotate_axis('Z',.4)
scene.render.filepath=str(out/'new_camera_atmosphere.png');bpy.ops.render.render(write_still=True)
report['changed_camera_rendered']=True
(out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('NATIVE_SEQUENCE_RENDER_VERIFIED',flush=True)
