"""Independent process, autoexec disabled; persisted weather, textures and cuts."""
import bpy,json,math
from pathlib import Path
rows=[]
for scene in bpy.data.scenes:
    mode=scene.get('earthstudio_weather_clock_mode')
    if not mode:continue
    bpy.context.window.scene=scene
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    values=[]
    for frame in [1,2,30,60,120,200]:
        scene.frame_set(frame);hour=control.path_resolve(path);values.append(hour)
        formal=next(o for o in scene.objects if o.get('earthstudio_layered_atmosphere') and not o.get('earthstudio_preview_proxy'))
        textures=[n for n in formal.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE' and n.image.source=='SEQUENCE']
        expected=min(3,max(1,math.floor(hour*6+1.00001)))
        assert all(frame+n.image_user.frame_offset==expected for n in textures)
    if scene.name.endswith('｜C'):assert max(values)==min(values)
    rows.append(dict(scene=scene.name,mode=mode,weather_hours=values))
assert len(rows)==3
montage=next(s for s in bpy.data.scenes if s.name.startswith('00｜连续成片 · 导入分镜'))
strips=list(montage.sequence_editor.strips)
assert all(strips[i].frame_final_end==strips[i+1].frame_final_start for i in range(len(strips)-1))
Path(bpy.data.filepath).with_suffix('.reopen.json').write_text(json.dumps(dict(passed=True,no_autoexec=True,rows=rows,consecutive_cuts=True),ensure_ascii=False,indent=2),encoding='utf-8')
print('MIXED_CLOCK_FRESH_REOPEN_PASSED',flush=True)
