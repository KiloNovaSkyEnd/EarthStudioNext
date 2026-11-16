"""Frame-exact shot cameras/weather and shared project look, without runtime handlers."""
import bisect,csv,json,math,re,time
from datetime import datetime,timezone
from pathlib import Path
import bpy
from scripts.blender_support.editable_camera import curves
from scripts.blender_support.scan_policy import safe_scan_index

def progress(stage,done,total,detail=''):
    print(json.dumps(dict(earthstudio_progress=True,stage=stage,done=done,total=total,detail=detail),ensure_ascii=False),flush=True)

def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def material_nodes(scene):
    seen=set()
    for obj in scene.objects:
        for slot in obj.material_slots:
            material=slot.material
            if not material or not material.node_tree or material.as_pointer() in seen:continue
            seen.add(material.as_pointer());yield material

def weather_manifest():
    for scene in bpy.data.scenes:
        for material in material_nodes(scene):
            for node in material.node_tree.nodes:
                if node.type=='TEX_IMAGE' and node.image:
                    path=Path(bpy.path.abspath(node.image.filepath)).resolve()
                    for parent in list(path.parents)[:4]:
                        manifest=parent/'sequence_manifest.json'
                        if manifest.is_file():return parent,json.loads(manifest.read_text(encoding='utf-8'))
    raise ValueError('无法定位当前Blender所引用的sequence_manifest.json；保留原工程')

def identity(track):return track.get('keyframeTrack',{}).get('asset',{}).get('id') or track.get('keyframeTrack',{}).get('id') or track['name']

def configure_scene(scene,track,manifest,root,free_camera,style=None):
    from scripts.blender_support.airglow_visibility import repair_all
    repair_all()
    from ges_next.camera import validate
    validate(track)
    control=bpy.data.objects[scene.camera['earthstudio_controller']]
    # Sampled ECEF poses are the interchange authority. Do not reinterpret browser
    # angle unwrap/easing with another sparse Euler rig in Blender.
    free_camera(scene.camera,track);scene.camera.data.sensor_fit='HORIZONTAL';scene.camera.data.sensor_width=36
    scene.render.fps=round(track['fps']);scene.render.fps_base=round(track['fps'])/track['fps']
    if abs(scene.render.resolution_x/scene.render.resolution_y-track['samples'][0]['aspect'])>1e-6:
        scene.render.resolution_x=track['samples'][0]['width'];scene.render.resolution_y=track['samples'][0]['height']
    scene.render.pixel_aspect_x=scene.render.pixel_aspect_y=1
    scene['earthstudio_shot_id']=identity(track);scene['earthstudio_camera_edit_mode']='frame_exact_ecef'
    scene.frame_start=1;scene.frame_end=round(track['samples'][-1]['seconds']*track['fps'])+1
    nodes=manifest['nodes'];times=[stamp(n['utc']) for n in nodes]
    # Export safety overrides legacy "blank" settings, including projects with
    # no movie preview. Never bake a known missing node into a renderable shot.
    policy='hold-last-labeled';scene['weather_gap_display_policy']=policy
    previous=[];valid=None
    for i,node in enumerate(nodes):
        if not node['missing']:valid=i
        previous.append(valid)
    control['earthstudio_scan_index']=1.0;path='["earthstudio_scan_index"]'
    weather_path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    if control.animation_data and control.animation_data.action:
        for curve in curves(control):
            if curve.data_path in (path,weather_path):curve.keyframe_points.clear()
    rows=[]
    for sample in track['samples']:
        planned=sample.get('timelineUtc') or sample.get('requestedObservationUtc') or sample.get('utc')
        if not planned:raise ValueError('镜头帧缺少计划UTC；不能静默复制第一镜头云图')
        frame=1+round(sample['seconds']*track['fps']);wanted=stamp(planned)
        if not times[0]-.001<=wanted<=times[-1]+.001:raise ValueError('当前Blender素材UTC范围不包含新镜头，原工程保留；请先更新对应素材')
        nominal=max(0,min(len(nodes)-1,bisect.bisect_right(times,wanted+1e-4)-1));actual=nominal
        actual=safe_scan_index(nodes,nominal,previous)
        control['earthstudio_scan_index']=float(actual+1);control.keyframe_insert(path,frame=frame)
        owner,attribute=weather_path.rsplit('.',1);setattr(control.path_resolve(owner),attribute,(wanted-times[0])/3600);control.keyframe_insert(weather_path,frame=frame)
        rows.append(dict(shot_id=identity(track),shot=track['name'],scene=scene.name,frame=frame,seconds=sample['seconds'],planned_utc=planned,nominal_index=nominal+1,actual_index=actual+1,actual_utc=nodes[actual]['utc'],missing=nodes[nominal]['missing'],display_policy=policy))
    for curve in curves(control):
        if curve.data_path==path:
            curve.extrapolation='CONSTANT'
            for point in curve.keyframe_points:point.interpolation='CONSTANT'
    local_images={}
    for material in list(material_nodes(scene)):
        # Old projects may have shared materials; make node drivers shot-local.
        if material.users>1:
            new=material.copy()
            for obj in scene.objects:
                for slot in obj.material_slots:
                    if slot.material==material:slot.material=new
            material=new
        tree=material.node_tree
        for node in tree.nodes:
            if node.type!='TEX_IMAGE' or not node.image:continue
            original=node.image;absolute=str(Path(bpy.path.abspath(original.filepath)).resolve())
            if original.source=='SEQUENCE':
                first_path=Path(absolute);digits=re.search(r'(\d+)(\.[^.]+)$',first_path.name)
                if not digits:raise ValueError('序列纹理缺少明确的帧编号：'+absolute)
                for index in {row['actual_index'] for row in rows}:
                    name=first_path.name[:digits.start(1)]+str(index).zfill(len(digits.group(1)))+digits.group(2)
                    required=first_path.with_name(name)
                    if not required.is_file() or required.stat().st_size==0:raise FileNotFoundError('镜头引用的正式扫描纹理缺失：'+str(required))
                key=original.as_pointer()
                if key not in local_images:
                    image=original.copy();image.filepath=absolute;local_images[key]=image
                node.image=local_images[key]
                user=node.image_user;user.frame_start=1;user.frame_duration=1000000;user.use_auto_refresh=True;user.use_cyclic=False
                try:user.driver_remove('frame_offset')
                except (TypeError,RuntimeError):pass
                driver=user.driver_add('frame_offset').driver;driver.type='SCRIPTED'
                variable=driver.variables.new();variable.name='idx';variable.targets[0].id=control;variable.targets[0].data_path=path
                # Blender stores at most255 expression characters. Gap handling is
                # baked into a native F-curve, never a growing expression string.
                driver.expression='idx-frame'
            elif not Path(absolute).is_file():raise FileNotFoundError('正式纹理缺失：'+absolute)
            else:original.filepath=absolute
        if style and tree.animation_data:
            weather_paths={json.loads(control['earthstudio_parameter_paths']).get('["weatherHours"]'),path}
            for curve in tree.animation_data.drivers:
                if '.image_user.' in curve.data_path:continue
                for variable in curve.driver.variables:
                    for target in variable.targets:
                        if target.id==control and target.data_path not in weather_paths:target.id=style
    scene['earthstudio_frame_map']=json.dumps(rows,ensure_ascii=False)
    keyset=scene.keying_sets.active or scene.keying_sets.new(idname='FrameExactCamera',name='记录当前相机姿态与焦距')
    keyset.paths.clear();keyset.paths.add(scene.camera,'location');keyset.paths.add(scene.camera,'rotation_quaternion');keyset.paths.add(scene.camera.data,'lens')
    keyset.bl_label='记录当前相机姿态与焦距'
    from scripts.blender_support.preview_controls import bind
    bind(scene)
    scene.frame_set(1);return rows

def shared_style(scenes):
    existing=next((o for o in bpy.data.objects if o.get('earthstudio_shared_look')),None)
    if existing:style=existing
    else:
        control=bpy.data.objects[scenes[0].camera['earthstudio_controller']]
        style=control.copy();style.name='00｜全片大气与地面（所有镜头共用）';style.animation_data_clear();style['earthstudio_shared_look']=True
        paths=json.loads(style['earthstudio_parameter_paths'])
        saved_values={path:style.path_resolve(path) for path in paths.values()}
        for modifier in style.modifiers:
            if modifier.type!='NODES' or not modifier.node_group:continue
            modifier.node_group=modifier.node_group.copy()
            hidden={re.search(r'inputs\.([^\.]+)\.value',paths.get('["'+key+'"]','')).group(1) for key in ['targetLon','targetLat','heading','pitch','rangeKm','roll','fov','weatherHours'] if re.search(r'inputs\.([^\.]+)\.value',paths.get('["'+key+'"]',''))}
            for socket in modifier.node_group.interface.items_tree:
                if getattr(socket,'identifier',None) in hidden and hasattr(socket,'hide_in_modifier'):socket.hide_in_modifier=True
        for path,value in saved_values.items():
            owner,attribute=path.rsplit('.',1);setattr(style.path_resolve(owner),attribute,value)
    for scene in scenes:
        if style.name not in scene.objects:scene.collection.objects.link(style)
        scene['earthstudio_shared_look']=style.name
    return style

def finalize(data,results,target,free_camera):
    root,manifest=weather_manifest();tracks=data['tracks'] if data.get('schema')=='earthstudio.camera_bundle.v1' else [data]
    scenes=[bpy.data.scenes[r['scene']] for r in results];style=shared_style(scenes);rows=[];edit_start=1
    for i,(scene,track) in enumerate(zip(scenes,tracks)):
        progress('逐镜头相机与UTC映射',i,len(tracks),track['name']);shot_rows=configure_scene(scene,track,manifest,root,free_camera,style)
        count=round(track['samples'][-1]['seconds']*track['fps']);clip=track.get('keyframeTrack',{}).get('clip') or dict(inFrame=0,outFrame=count)
        for row in shot_rows:
            local=row['frame']-1;row['planned_edit_frame']=edit_start+local-clip['inFrame'] if clip['inFrame']<=local<clip['outFrame'] else None
        edit_start+=clip['outFrame']-clip['inFrame'];scene['earthstudio_frame_map']=json.dumps(shot_rows,ensure_ascii=False);rows+=shot_rows
    # Add stable shot provenance independent of overlapping UTC/time ordering.
    path=target.with_suffix('.frames.csv');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    bpy.data.texts.get('全镜头逐帧UTC映射.json') or bpy.data.texts.new('全镜头逐帧UTC映射.json')
    text=bpy.data.texts['全镜头逐帧UTC映射.json'];text.clear();text.write(json.dumps(rows,ensure_ascii=False,indent=2))
    scene_map=[dict(scene=s.name,shot_id=identity(t),name=t['name'])for s,t in zip(scenes,tracks)]
    for scene in scenes:scene['earthstudio_frame_map_file']=str(path)
    for montage in bpy.data.scenes:
        if not montage.get('earthstudio_montage') or not montage.sequence_editor:continue
        strips=sorted([s for s in montage.sequence_editor.strips if s.type=='SCENE' and s.scene in scenes],key=lambda s:s.frame_final_start)
        if not strips:continue
        reference=strips[0].scene
        montage['earthstudio_previous_color_management']=json.dumps(dict(view=montage.view_settings.view_transform,look=montage.view_settings.look,exposure=montage.view_settings.exposure,gamma=montage.view_settings.gamma))
        for key in ('view_transform','look','exposure','gamma'):setattr(montage.view_settings,key,getattr(reference.view_settings,key))
        montage.sequencer_colorspace_settings.name=reference.sequencer_colorspace_settings.name
    target.with_suffix('.camera.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    if data.get('timelineProject'):target.with_suffix('.timeline.json').write_text(json.dumps(data['timelineProject'],ensure_ascii=False,indent=2),encoding='utf-8')
    helptext=bpy.data.texts.get('M18｜运镜更新与全片外观说明') or bpy.data.texts.new('M18｜运镜更新与全片外观说明');helptext.clear()
    helptext.write('所有导入镜头的大气/气辉/地面外观统一由对象“'+style.name+'”控制。请选此对象的修改器调节，全部镜头共用。\n镜头姿态与天气索引独立，按导出的每帧ECEF姿态和UTC读取。\n同目录.timeline.json可在摄影棚“打开运镜工程”恢复完整运镜；.camera.json是导入快照；.frames.csv记录镜头ID、本地帧、计划UTC、实际扫描和缺档显示。\n回到软件修改后，用“更新已有Blender运镜”选择当前艺术工程，保存修订副本；原工程不覆盖。\n真实缺档不会冒充观测；保持上一帧时请查看逐帧表中的missing与actual_utc。')
    for scene in scenes:
        scene.view_layers[0].objects.active=style
        for obj in scene.objects:obj.select_set(obj==style)
    progress('逐镜头相机与UTC映射',len(tracks),len(tracks));return scene_map

def update_bundle(data,target,free_camera):
    tracks=data['tracks'] if data.get('schema')=='earthstudio.camera_bundle.v1' else [data]
    existing=[s for s in bpy.data.scenes if str(s.get('earthstudio_scene_track','')).startswith('WEB_')]
    if any(not s.get('layered_weather_sequence') for s in existing):raise ValueError('此更新入口支持JPG分层运镜工程；其他旧模板保留，请使用对应导出入口')
    by_id={s.get('earthstudio_shot_id'):s for s in existing if s.get('earthstudio_shot_id')};results=[]
    for i,track in enumerate(tracks,1):
        scene=by_id.get(identity(track))
        if not scene:scene=next((s for s in existing if not s.get('earthstudio_shot_id') and s.get('earthstudio_scene_track')=='WEB_'+str(i) and s.name.split('｜',1)[-1]==track['name']),None)
        if not scene:raise ValueError('旧工程缺少稳定对应镜头：'+track['name']+'；保留原文件，请首次生成包含该镜头的工程')
        results.append(dict(scene=scene.name,track=track['name']))
    if target.exists():raise FileExistsError('目标已存在；旧工程保留')
    finalize(data,results,target,free_camera)
    text=bpy.data.texts.get('网页相机原始导出.json') or bpy.data.texts.new('网页相机原始导出.json');text.clear();text.write(json.dumps(data,ensure_ascii=False,indent=2))
    bpy.context.window.scene=bpy.data.scenes[results[0]['scene']]
    progress('保存Blender（保留艺术设置）',0,1)
    bpy.ops.wm.save_as_mainfile(filepath=str(target),relative_remap=True)
    target.with_suffix('.import.json').write_text(json.dumps(dict(project=str(target),scenes=results,update=True),ensure_ascii=False,indent=2),encoding='utf-8')
    progress('完成',1,1,str(target))
