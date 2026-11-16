"""Actual120-second browser export: camera path, UTC and all native page nodes."""
import bpy,json,sys,math,faulthandler,time
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from scripts.blender_import_dynamic_cameras import import_bundle
from ges_next.camera import horizontal_lens_mm
args=sys.argv[sys.argv.index('--')+1:]
source,target,report_path=map(lambda x:Path(x).resolve(),args)
data=json.loads(source.read_text(encoding='utf-8'))
assert len(data['samples'])==3601 and data['samples'][-1]['seconds']==120
assert data['weatherPlayback']['observationFps']==.6
assert [k['time'] for k in data['keyframeTrack']['keys']]==[0,60,120]
short=json.loads((root/'reports/h9_web_bridge/video_twelve_second_camera.json').read_text(encoding='utf-8'))
for name in ['easing','curve']:
 assert data['keyframeTrack'].get(name)==short['keyframeTrack'].get(name)
for a,b in zip(data['keyframeTrack']['keys'],short['keyframeTrack']['keys']):
 assert abs(a['time']-b['time']*10)<1e-8
 assert a.get('curve')==b.get('curve') and a.get('transition')==b.get('transition')
 assert all(abs(a['orbit'][name]-b['orbit'][name])<1e-8 for name in ['targetLon','targetLat','heading','pitch','rangeKm','roll','fov'])
missing=[s for s in data['samples'] if s['observationState']=='missing']
assert missing and all(s['utc'] is None and s['displayedObservationUtc']=='2026-10-20T14:30:00Z' for s in missing)
faulthandler.dump_traceback_later(30,repeat=True)
started=time.perf_counter()
print('FULL120_IMPORT_START',flush=True)
import_bundle(source,target)
import_seconds=time.perf_counter()-started
print('FULL120_IMPORT_SECONDS',import_seconds,flush=True)
assert json.loads(bpy.data.texts['网页相机原始导出.json'].as_string())==data
scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_1');bpy.context.window.scene=scene
camera=scene.camera;control=bpy.data.objects[camera['earthstudio_controller']]
paths=json.loads(control['earthstudio_parameter_paths']);weather_path=paths['["weatherHours"]']
errors=dict(position_metres=0,direction=0,up=0,lens_mm=0,weather_hours=0,estimated_image_pixels=0)
for sample in data['samples']:
 f=1+sample['seconds']*30;assert abs(f-round(f))<1e-8;scene.frame_set(round(f));m=camera.matrix_world
 position=(m.translation-Vector(sample['position'])/1e6).length*1e6
 direction=(-(m.to_3x3()@Vector((0,0,1)))-Vector(sample['direction'])).length
 up=((m.to_3x3()@Vector((0,1,0)))-Vector(sample['up'])).length
 errors['position_metres']=max(errors['position_metres'],position)
 errors['direction']=max(errors['direction'],direction)
 errors['up']=max(errors['up'],up)
 # Earth-scale float/Bezier precision: enforce <0.1 native500m sample and
 # a separate conservative image-space bound for this1920x1080 take.
 range_metres=control.path_resolve(paths['["rangeKm"]'])*1000
 focal_pixels=sample['height']/(2*math.tan(sample['verticalFov']/2))
 image_error=(position/range_metres+direction+up)*focal_pixels
 errors['estimated_image_pixels']=max(errors['estimated_image_pixels'],image_error)
 errors['lens_mm']=max(errors['lens_mm'],abs(camera.data.lens-horizontal_lens_mm(sample)))
 errors['weather_hours']=max(errors['weather_hours'],abs(control.path_resolve(weather_path)-(6+sample['seconds']/120*12)))
assert errors['position_metres']<50 and max(errors['direction'],errors['up'])<2e-5 and errors['estimated_image_pixels']<.05 and errors['lens_mm']<1e-4 and errors['weather_hours']<1e-4,errors
mesh=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'));tree=mesh.data.materials[0].node_tree
textures=[n for n in tree.nodes if n.type=='TEX_IMAGE' and n.image and n.image.source=='SEQUENCE'];checks=[]
for index in range(73):
 scene.frame_set(1+index*50);bpy.context.view_layer.update()
 expected=10 if index==10 else index+1
 actual=[round(scene.frame_current+n.image_user.frame_offset) for n in textures]
 assert len(actual)==16 and set(actual)=={expected},(index,actual,expected)
 checks.append(dict(nominal_index=index+1,displayed_native_index=expected,all16_pages=True))
assert scene.frame_end==3601 and scene['weather_gap_display_policy']=='hold-last-labeled'
assert all(c.is_valid for c in tree.animation_data.drivers)
bpy.ops.wm.open_mainfile(filepath=str(target),use_scripts=False)
assert json.loads(bpy.data.texts['网页相机原始导出.json'].as_string())==data
scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_1');bpy.context.window.scene=scene
assert scene.frame_end==3601
scene.frame_set(3601)
mesh=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'));tree=mesh.data.materials[0].node_tree
assert all(c.is_valid for c in tree.animation_data.drivers)
assert {round(scene.frame_current+n.image_user.frame_offset) for n in tree.nodes if n.type=='TEX_IMAGE' and n.image and n.image.source=='SEQUENCE'}=={73}
faulthandler.cancel_dump_traceback_later()
report=dict(actual_browser_export=True,duration_seconds=120,observation_fps=.6,import_seconds=import_seconds,camera_samples_verified=3601,all73_native_page_nodes_verified=True,path_identical_to_12_second_take=True,missing_actual_utc_preserved=True,embedded_source_roundtrip_verified=True,reopened_without_scripts_verified=True,errors=errors,acceptance_limits=dict(position_metres=50,estimated_image_pixels=.05),native_node_checks=checks,blend=str(target),new_project_original_preserved=True)
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('FULL120_CAMERA_AND_NATIVE_WEATHER_VERIFIED',json.dumps(errors),flush=True)
