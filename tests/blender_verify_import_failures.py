"""Reject bad bundles before scene changes; preserve source assets and outputs."""
import bpy,json,sys,copy,importlib.util,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.camera import horizontal_lens_mm
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dynamic_import',root/'scripts/blender_import_dynamic_cameras.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
out=root/'reports/h9_web_bridge/failure_tests';out.mkdir(exist_ok=True)
bundle=json.loads((root/'reports/h9_web_bridge/actual_browser_bundle.json').read_text(encoding='utf-8'))
before=set(bpy.data.scenes.keys());results=[]
def reject(name,data,expected):
    source=out/(name+'.json');source.write_text(json.dumps(data),encoding='utf-8')
    target=out/(name+'.blend')
    try:module.import_bundle(source,target)
    except expected as error:results.append(dict(case=name,rejected=True,reason=str(error)))
    else:raise AssertionError(name+' should fail')
    assert set(bpy.data.scenes.keys())==before and not target.exists()

reject('wrong_document',[],ValueError)
bad=copy.deepcopy(bundle);bad['tracks'][1]['keyframeTrack']['keys'][0]['curve']=[[0,0],[0,.5],[1,1]]
reject('duplicate_curve_time_second_track',bad,ValueError)
bad=copy.deepcopy(bundle);bad['tracks'][0]['effects']['blueAtmosphere']='false'
reject('string_boolean',bad,ValueError)
bad=copy.deepcopy(bundle);bad['tracks'][0]['samples'][0]['up']=[0,0,0]
reject('invalid_free_pose_basis',bad,ValueError)
bad=copy.deepcopy(bundle);bad['tracks'][0]['timelineProject']['weather']['startUtc']='2026-10-20T12:00:00Z'
reject('weather_outside_assets',bad,ValueError)
source=out/'valid.json';source.write_text(json.dumps(bundle),encoding='utf-8')
target=out/'existing.blend';target.write_bytes(b'existing-user-project')
try:module.import_bundle(source,target)
except FileExistsError:results.append(dict(case='existing_output',rejected=True))
else:raise AssertionError('Existing output overwritten')
assert target.read_bytes()==b'existing-user-project' and set(bpy.data.scenes.keys())==before
real_is_file=Path.is_file
with patch.object(Path,'is_file',lambda path:False if path.name=='weather_0073.tif' else real_is_file(path)):
    reject('missing_last_weather_asset',bundle,FileNotFoundError)

# Non-default output aspect must update both lens driver and render canvas.
single=copy.deepcopy(bundle);single['tracks']=single['tracks'][:1]
for sample in single['tracks'][0]['samples']:
    sample['width'],sample['height'],sample['aspect']=1600,1200,4/3
source=out/'aspect_4_3.json';source.write_text(json.dumps(single),encoding='utf-8')
module.import_bundle(source,out/('aspect_4_3_'+str(time.time_ns())+'.blend'))
scene=bpy.context.scene;scene.frame_set(1)
assert (scene.render.resolution_x,scene.render.resolution_y)==(1600,1200)
assert abs(scene.camera.data.lens-horizontal_lens_mm(single['tracks'][0]['samples'][0]))<1e-4
assert all((bpy.data.scenes[name].render.resolution_x,bpy.data.scenes[name].render.resolution_y)==(1920,1080) for name in before)
results.append(dict(case='output_4_3',canvas=[1600,1200],lens_correct=True,original_scenes_preserved=True))
(out/'verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('IMPORT_FAILURES_AND_NONDEFAULT_ASPECT_VERIFIED',flush=True)
