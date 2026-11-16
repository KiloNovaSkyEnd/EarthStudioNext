"""Self-contained layered JPEG animation, retaining the accepted editable rig."""
import json
import copy
from pathlib import Path
import sys
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from ges_next.production.assets import verify_assets
from scripts.blender_support.dual_airglow import create
from scripts.blender_support.layered_weather_clock import attach


def main():
    root=Path(sys.argv[sys.argv.index('--')+1]).resolve()
    sequence=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'))
    single=len(sequence['nodes'])==1
    target=require_writable(root/('EarthStudio_JPG_单帧.blend' if single else 'EarthStudio_JPG_动画.blend'))
    if target.exists():raise FileExistsError('Existing animation preserved')
    sequence=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'));verify_assets(root,sequence['files']+sequence['auxiliary_files'])
    if not sequence['nodes']:raise ValueError('至少需要一个真实观测时次')
    master=json.loads((root/'native_master.json').read_text(encoding='utf-8'));temporal=master['production_sequence']
    for obj in list(bpy.data.objects):
        if obj.get('earthstudio_layered_atmosphere') or obj.get('earthstudio_preview_proxy'):
            bpy.data.objects.remove(obj,do_unlink=True)
    project_settings=None
    for scene in bpy.data.scenes:
        bpy.context.window.scene=scene
        control=bpy.data.objects[scene.camera['earthstudio_controller']]
        paths=attach(control,scene,temporal['clock_start'],temporal['clock_end'])
        if not single:
            from scripts.blender_support.weather_fps import configure
            interval=(temporal['clock_end']-temporal['clock_start'])*3600/(len(sequence['nodes'])-1)
            seconds=(scene.frame_end-scene.frame_start)/(scene.render.fps/scene.render.fps_base)
            configure(scene,temporal['clock_start'],temporal['clock_end'],interval,scene.render.fps/scene.render.fps_base)
            from scripts.blender_support.weather_fps import apply_scene
            from scripts.blender_support.project_clock import configure as configure_project,apply_clock
            project_settings=configure_project(scene,scene.render.fps/scene.render.fps_base,project_settings);apply_clock(scene)
        master['production_control']=control.name
        sun=sequence['suns'][0] if single else dict(vectors=sequence['suns'],clock_start=temporal['clock_start'],clock_end=temporal['clock_end'])
        formal=create(scene,master,root,{},sun,control,paths)
        lightweight=copy.deepcopy(master);lightweight['production_layers']=master['preview_layers']
        proxy=create(scene,lightweight,root,{},sun,control,paths);proxy['earthstudio_preview_proxy']=True;proxy.hide_render=True
        for obj,invert in ((formal,True),(proxy,False)):
            driver=obj.driver_add('hide_viewport').driver;var=driver.variables.new();var.name='high'
            var.targets[0].id=control;var.targets[0].data_path=paths['["previewHigh"]']
            driver.expression='not high' if invert else 'high'
        scene['earthstudio_preview_label']='PLAYBACK PROXY 1024 | FINAL: 11K JPEG'
        scene['production_single_scan']=single;scene['layered_weather_sequence']=True
        scene['weather_start_utc']=sequence['nodes'][0]['utc'];scene['weather_end_utc']=sequence['nodes'][-1]['utc']
        scene['weather_gap_display_policy']='blank';scene['weather_native_sequence']=True
        for marker in list(scene.timeline_markers):
            if marker.name.startswith(('天气','缺档')):scene.timeline_markers.remove(marker)
        for node in sequence['nodes']:
            frame=scene.frame_start if single else round(scene.frame_start+(node['index']-1)/(len(sequence['nodes'])-1)*(scene.frame_end-scene.frame_start))
            scene.timeline_markers.new(('缺档 ' if node['missing'] else '天气 ')+node['utc'],frame=frame)
        scene.render.filepath='//renders/'+scene.name.replace('｜','_')+'/frame_'
        scene.frame_set(scene.frame_start)
    allowed={(root/a['path']).resolve() for a in sequence['files']+sequence['auxiliary_files'] if a['role']!='source-provenance'}
    for image in list(bpy.data.images):
        if image.source in ('FILE','MOVIE','SEQUENCE'):
            path=Path(bpy.path.abspath(image.filepath)).resolve()
            if path not in allowed:bpy.data.images.remove(image,do_unlink=True)
            else:image.filepath='//'+path.relative_to(root).as_posix()
    bpy.data.texts.new('00｜JPG动态天气说明').write('正式JPG分层序列，必要遮罩为无损PNG。天气经过0代表本素材起点，真实UTC在时间标记中；单位小时。相机时长与天气范围独立；天气曲线可改速度。地面夜景、蓝色大气、夜间气辉独立控制。缺档灰色；不生成虚假观测。保留整个assets文件夹，无需L1或自动运行脚本。')
    from scripts.blender_support.montage import create as create_montage
    montage,plan=create_montage()
    bpy.context.window.scene=next(s for s in bpy.data.scenes if s.get('layered_weather_sequence'))
    (root/'edit_list.json').write_text(json.dumps(dict(clips=plan),ensure_ascii=False,indent=2),encoding='utf-8')
    from scripts.blender_support.airglow_visibility import repair_all
    repair_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(target),relative_remap=False)
    print('LAYERED_ANIMATION_READY',target,flush=True)


if __name__=='__main__':main()
