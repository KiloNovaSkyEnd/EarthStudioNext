"""Actual 73 nominal weather nodes and editable camera motion, preview only."""
import bpy,sys,math,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.gpu import configure
out=Path(sys.argv[sys.argv.index('--')+1]);out.mkdir(exist_ok=True,parents=True)
scene=list(bpy.data.scenes)[2];bpy.context.window.scene=scene
configure(scene);scene.cycles.samples=8;scene.cycles.adaptive_min_samples=8
scene.render.resolution_x,scene.render.resolution_y=640,360;scene.render.resolution_percentage=100
scene.render.use_persistent_data=False
records=[]
for index in range(73):
    f=scene.frame_start+index/72*(scene.frame_end-scene.frame_start)
    scene.frame_set(math.floor(f),subframe=f%1)
    path=out/f'preview_{index+1:04d}.png';scene.render.filepath=str(path)
    if not path.exists():bpy.ops.render.render(write_still=True)
    records.append(dict(preview_frame=index+1,blender_frame=f,weather_hours_utc_minus7=6+index/6,missing=index==10,camera_matrix=[list(row) for row in scene.camera.matrix_world]))
    (out/'preview_frames.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ANIMATED_REVIEW_FRAME',index+1,flush=True)
