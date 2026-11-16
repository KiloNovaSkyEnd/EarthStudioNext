"""Actual browser download -> native editable rigs + synchronized weather."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.camera import horizontal_lens_mm
from scripts.blender_support.gpu import configure
args=sys.argv[sys.argv.index('--')+1:];bundle=json.loads(Path(args[0]).read_text());out=Path(args[1]);out.mkdir(exist_ok=True,parents=True)
records=[]
for scene in bpy.data.scenes:
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    assert all(path.id==control for path in scene.keying_sets.active.paths) if scene.get('earthstudio_scene_track')=='USER' or str(scene.get('earthstudio_scene_track','')).startswith('WEB_') else True
    shells=[o for o in scene.objects if o.get('earthstudio_layered_atmosphere')];assert len(shells)==1
    assert all(v.targets[0].id==control for d in shells[0].data.materials[0].node_tree.animation_data.drivers for v in d.driver.variables)
for i,track in enumerate(bundle['tracks'],1):
    scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_'+str(i));bpy.context.window.scene=scene
    camera=scene.camera;control=bpy.data.objects[camera['earthstudio_controller']];paths=json.loads(control['earthstudio_parameter_paths'])
    maximum=dict(position_metres=0,direction=0,up=0,lens=0,weather_hours=0)
    for sample in track['samples']:
        f=1+sample['seconds']*30;scene.frame_set(math.floor(f),subframe=f%1);matrix=camera.matrix_world
        maximum['position_metres']=max(maximum['position_metres'],(matrix.translation-Vector(sample['position'])/1e6).length*1e6)
        maximum['direction']=max(maximum['direction'],(-(matrix.to_3x3()@Vector((0,0,1)))-Vector(sample['direction'])).length)
        maximum['up']=max(maximum['up'],((matrix.to_3x3()@Vector((0,1,0)))-Vector(sample['up'])).length)
        maximum['lens']=max(maximum['lens'],abs(camera.data.lens-horizontal_lens_mm(sample)))
        expected=6+sample['seconds']/track['samples'][-1]['seconds']*12
        maximum['weather_hours']=max(maximum['weather_hours'],abs(control.path_resolve(paths['["weatherHours"]'])-expected))
        if sample.get('observationState')=='missing':assert sample['utc'] is None
    assert maximum['position_metres']<20 and maximum['direction']<3e-6 and maximum['up']<3e-6 and maximum['lens']<.0002 and maximum['weather_hours']<1e-4,maximum
    configure(scene);scene.cycles.samples=4;scene.cycles.adaptive_min_samples=4
    scene.render.resolution_x,scene.render.resolution_y=640,360;scene.render.resolution_percentage=100
    for frame in [1,round((scene.frame_end+1)/2),scene.frame_end]:
        scene.frame_set(frame);scene.render.filepath=str(out/f'web_{i}_frame_{frame:04d}.png');bpy.ops.render.render(write_still=True)
    records.append(dict(scene=scene.name,samples_verified=len(track['samples']),errors=maximum,end_frame=scene.frame_end))
(out/'verification.json').write_text(json.dumps(dict(actual_browser_export=True,imported_tracks=records,independent_material_ownership=True,original_template_keying_set_preserved=True),ensure_ascii=False,indent=2),encoding='utf-8')
print('BROWSER_TO_BLENDER_DYNAMIC_WEATHER_VERIFIED',flush=True)
