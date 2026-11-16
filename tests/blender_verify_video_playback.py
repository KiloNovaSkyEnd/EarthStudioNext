import bpy,json,sys,math,hashlib
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from scripts.blender_import_dynamic_cameras import import_bundle
source=root/'reports/h9_web_bridge/video_twelve_second_camera.json'
data=json.loads(source.read_text(encoding='utf-8'))
assert data['weatherPlayback']['observationFps']==6
assert [k['time'] for k in data['keyframeTrack']['keys']]==[0,6,12]
missing=[s for s in data['samples'] if s.get('observationState')=='missing']
assert missing and all(s['utc'] is None and s['displayedObservationUtc']=='2026-10-20T14:30:00Z' for s in missing)
out=root/'data/exports/H9_20261020_12h_Blender_v1/user_projects/连续云图与12秒运镜验收.blend'
import_bundle(source,out)
scene=next(s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='WEB_1');bpy.context.window.scene=scene
camera=scene.camera
errors=dict(position_metres=0,direction=0,up=0)
for sample in data['samples']:
 f=1+sample['seconds']*30;scene.frame_set(math.floor(f),subframe=f%1)
 m=camera.matrix_world
 errors['position_metres']=max(errors['position_metres'],(m.translation-Vector(sample['position'])/1e6).length*1e6)
 errors['direction']=max(errors['direction'],(-(m.to_3x3()@Vector((0,0,1)))-Vector(sample['direction'])).length)
 errors['up']=max(errors['up'],((m.to_3x3()@Vector((0,1,0)))-Vector(sample['up'])).length)
assert errors['position_metres']<3 and max(errors['direction'],errors['up'])<2e-6,errors
mesh=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere'))
tree=mesh.data.materials[0].node_tree
textures=[n for n in tree.nodes if n.type=='TEX_IMAGE' and n.image and n.image.source=='SEQUENCE']
checks=[]
for index,expected in [(0,1),(9,10),(10,10),(11,12),(72,73)]:
 frame=1+index/72*12*30;scene.frame_set(round(frame));bpy.context.view_layer.update()
 actual=[round(scene.frame_current+n.image_user.frame_offset) for n in textures]
 assert len(actual)==16 and set(actual)=={expected},(index,actual,expected)
 checks.append(dict(nominal_index=index+1,displayed_native_index=expected,all_16_pages=True))
assert scene['weather_gap_display_policy']=='hold-last-labeled'
assert all(c.is_valid for c in tree.animation_data.drivers)
report=dict(actual_browser_camera=True,samples_verified=len(data['samples']),errors=errors,duration=12,observation_fps=6,missing_utc_preserved=True,native_page_selection=checks,blend=str(out))
(root/'reports/h9_web_bridge/video_blender_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('VIDEO_CAMERA_NATIVE_WEATHER_PASS',json.dumps(report,ensure_ascii=False),flush=True)
