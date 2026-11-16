"""Blender-only web-camera import into new independent native-weather scenes.

Run with the delivered dynamic blend loaded. No scientific runtime is imported.
"""
import bpy,json,sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
try:
    from editable_camera import parameter_points,curves,PARAMETERS
    from camera_contract import validate,basis,horizontal_lens_mm
except ImportError:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from scripts.blender_support.editable_camera import parameter_points,curves,PARAMETERS
    from ges_next.camera import validate,basis,horizontal_lens_mm

def free_camera(camera,track):
    """Native transform/lens curves, preserving every exported30fps sample."""
    from mathutils import Matrix
    camera.parent=None;camera.matrix_parent_inverse.identity()
    camera.hide_select=False
    camera.animation_data_clear();camera.data.animation_data_clear()
    # Separate actions prevent Blender from automatically sharing object/data slots.
    for owner,label in [(camera,'自由相机位置旋转'),(camera.data,'自由相机焦距')]:
        owner.animation_data_create();owner.animation_data.action=bpy.data.actions.new(label+' · '+track.get('name','分镜'))
    for constraint in list(camera.constraints):camera.constraints.remove(constraint)
    camera.rotation_mode='QUATERNION';previous=None
    for sample in track['samples']:
        frame=1+sample['seconds']*track['fps']
        right,up,back=basis(sample['direction'],sample['up'])
        rotation=Matrix((right,up,back)).transposed().to_quaternion()
        if previous is not None and rotation.dot(previous)<0:rotation.negate()
        previous=rotation.copy()
        camera.location=[v/1e6 for v in sample['position']];camera.rotation_quaternion=rotation
        camera.data.lens=horizontal_lens_mm(sample)
        camera.keyframe_insert('location',frame=frame);camera.keyframe_insert('rotation_quaternion',frame=frame)
        camera.data.keyframe_insert('lens',frame=frame)
    for owner in (camera,camera.data):
        for curve in curves(owner):
            curve.extrapolation='CONSTANT'
            for point in curve.keyframe_points:point.interpolation='LINEAR'

def validate_curve(points):
    if not isinstance(points,list) or not 2<=len(points)<=128:raise ValueError('速度曲线需要2–128个控制点')
    previous=(-1,-1)
    for point in points:
        if not isinstance(point,list) or len(point)!=2 or not all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in point):raise ValueError('速度曲线控制点必须在0–1范围内')
        if point[0]<=previous[0] or point[1]<previous[1]:raise ValueError('速度曲线时间须递增，路径进度不能倒退')
        previous=point
    if points[0]!=[0,0] or points[-1]!=[1,1]:raise ValueError('速度曲线必须从[0,0]到[1,1]')

def check_native_assets():
    sequences=[image for image in bpy.data.images if image.source=='SEQUENCE']
    if not sequences:
        if not any(s.get('layered_weather_sequence') and s.get('production_single_scan') for s in bpy.data.scenes):
            raise ValueError('请通过工具加载已交付的天气模板')
        # A single weather observation is a FILE texture, while its camera still
        # has an editable animation. Do not require fabricated weather frames.
        sequences=[image for image in bpy.data.images if image.source=='FILE'
                   and Path(bpy.path.abspath(image.filepath)).resolve().parents[1].name=='assets']
    if not sequences:raise ValueError('单帧素材缺少正式图层')
    root=Path(bpy.path.abspath(sequences[0].filepath)).resolve().parents[2]
    manifest=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'))
    entries=manifest['files']+manifest.get('auxiliary_files',[])
    from scripts.blender_support.roundtrip import progress
    total=sum(e['bytes'] for e in entries);done=0
    progress('校验正式素材',0,total)
    for entry in entries:
        path=root/entry['path']
        if not path.is_file() or path.stat().st_size!=entry['bytes']:raise FileNotFoundError('原生天气素材缺失或大小不符，请恢复完整assets文件夹：'+str(path))
        if manifest['schema']=='earthstudio.layered_weather_sequence.v1':
            with path.open('rb') as stream:
                if __import__('hashlib').file_digest(stream,'sha256').hexdigest()!=entry['sha256']:raise ValueError('JPG分层素材内容已改变')
        done+=entry['bytes']
        progress('校验正式素材',done,total,entry['path'])
    return manifest


def gap_hold_expression(nodes,step_seconds=600,clock_start=6):
    """Display-only hold; retain the actual UTC clock and native missing files."""
    nominal=f'min({len(nodes)},max(1,floor((hours-{clock_start})*{3600/step_seconds!r}+1.00001)))'
    previous=None;corrections=[]
    for node in nodes:
        index=node['index']
        if node['missing']:
            if previous is None:raise ValueError('Cannot hold a leading missing observation')
            corrections.append(f'({index-previous})*({nominal}=={index})')
        else:previous=index
    return nominal+''.join('-'+term for term in corrections)+'-min(1000000,max(0,frame))'

def import_bundle(source,target):
    data=json.loads(source.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict):raise ValueError('请选择网页导出的相机JSON，不能使用其他文件')
    tracks=data['tracks'] if data.get('schema')=='earthstudio.camera_bundle.v1' else [data]
    if not isinstance(tracks,list) or not 1<=len(tracks)<=100:raise ValueError('Requires1–100 camera tracks')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from scripts.blender_support.dual_airglow import upgrade_all
    upgrade_all()
    from scripts.blender_support.airglow_visibility import repair_all as repair_airglow
    repair_airglow()
    template=next((s for s in bpy.data.scenes if s.get('earthstudio_scene_track')=='USER'),None)
    if template is None:raise ValueError('请通过导入工具加载已交付的动态天气模板')
    has_movie_preview=any(o.get('earthstudio_preview_proxy') for o in template.objects) and not template.get('layered_weather_sequence')
    native_manifest=check_native_assets()
    if not template.get('layered_weather_sequence') and any(n['missing'] for n in native_manifest['nodes']):
        raise ValueError('旧PNG/TIFF模板包含缺测节点，已停止导出以避免空地球；请使用JPG分层素材的缺测保护导出入口')
    clock_start=0 if template.get('layered_weather_sequence') else 6
    master_start=__import__('datetime').datetime.fromisoformat(template['weather_start_utc'].replace('Z','+00:00'))
    prepared=[]
    for track in tracks:
        if not isinstance(track,dict):raise ValueError('相机分镜格式错误')
        validate(track)
        keytrack=track.get('keyframeTrack',{})
        if not isinstance(keytrack,dict):raise ValueError('关键帧格式错误')
        keys=keytrack.get('keys',[])
        if not isinstance(keys,list) or any(not isinstance(k,dict) for k in keys):raise ValueError('关键帧格式错误')
        orbit_mode=bool(keys and all(k.get('orbit') for k in keys))
        previous=-1
        duration=track['samples'][-1]['seconds']
        if duration<=0:raise ValueError('运镜时长必须大于0秒')
        if keytrack.get('curve') is not None:validate_curve(keytrack['curve'])
        for key in keys:
            t=key['time']
            if type(t) not in (int,float) or not math.isfinite(t) or not previous<t or not 0<=t<=duration+1e-4:raise ValueError('Invalid keyframe time')
            previous=t
            if key.get('curve') is not None:validate_curve(key['curve'])
            if not orbit_mode:continue
            if not all(type(key['orbit'].get(p)) in (int,float) and math.isfinite(key['orbit'][p]) for p in PARAMETERS):raise ValueError('Invalid orbit parameter')
            if not (-179.9<=key['orbit']['pitch']<=-0.1 and -89.999<=key['orbit']['targetLat']<=89.999 and 100<=key['orbit']['rangeKm']<=50000 and 1<=key['orbit']['fov']<=150):raise ValueError('Orbit outside supported camera ranges')
        weather=keytrack.get('weather') or track.get('timelineProject',data.get('timelineProject',{})).get('weather')
        if not weather:raise ValueError('Absolute weather UTC range required')
        project_clock=track.get('timelineProject',data.get('timelineProject',{}))
        source_clock=project_clock.get('sourcePlayback')
        if source_clock and weather.get('mode')!='mapped':
            if source_clock.get('mode')!='sequence' or project_clock.get('fps')!=track['fps']:raise ValueError('Project source clock/fps mismatch')
            weather=dict(startUtc=weather['startUtc'],endUtc=project_clock['weather']['endUtc'],observationFps=project_clock['fps'],intervalSeconds=source_clock['intervalSeconds'],projectClock=True)
        weather_curve=weather.get('curve')
        if 'observationFps' in weather:
            from scripts.blender_support.weather_fps import seconds_for
            seconds_for(0,1,weather.get('intervalSeconds',0),weather['observationFps'])
            if weather_curve:raise ValueError('Fixed rate and weather curve cannot both be active')
        if weather_curve is not None:validate_curve(weather_curve)
        hours=[]
        for endpoint in ['startUtc','endUtc']:
            label=weather[endpoint]
            if not label.endswith('Z'):raise ValueError('UTC Z required')
            stamp=__import__('datetime').datetime.fromisoformat(label.replace('Z','+00:00'))
            hours.append(clock_start+(stamp-master_start).total_seconds()/3600)
        material_end=__import__('datetime').datetime.fromisoformat(template.get('weather_end_utc','2026-10-21T01:00:00Z').replace('Z','+00:00'))
        if not clock_start<=hours[0]<=hours[1]<=clock_start+(material_end-master_start).total_seconds()/3600+1e-8:raise ValueError('Weather interval outside delivered H9 material')
        effects=track.get('effects',{})
        if not isinstance(effects,dict) or any(name in effects and type(effects[name]) is not bool for name in ['blueAtmosphere','nightAirglow','newAirglow']):raise ValueError('大气开关必须是布尔值')
        from scripts.blender_support.dual_airglow import CONTROLS
        for key,_,_,lo,hi in CONTROLS[1:]:
            if key in effects and (type(effects[key]) not in (int,float) or not math.isfinite(effects[key]) or not lo<=effects[key]<=hi):raise ValueError('新版气辉参数超出范围：'+key)
        playback=track.get('weatherPlayback',{})
        if not isinstance(playback,dict) or playback.get('gapPolicy','blank') not in ('blank','hold-last-labeled'):raise ValueError('不支持的缺档显示策略')
        gap_policy=playback.get('gapPolicy',template.get('weather_gap_display_policy','blank'))
        if has_movie_preview and gap_policy!='hold-last-labeled':raise ValueError('11K连续预览采用标注保持缺档；如需透明缺档请使用22K导入入口')
        # Build/validate all parameter curves before mutating any Blender scene.
        if orbit_mode:
            for parameter in PARAMETERS:parameter_points(keys,parameter,track['keyframeTrack'],track['fps'])
        prepared.append((track,hours,orbit_mode,gap_policy,weather_curve,weather))
    if target.exists():raise FileExistsError('Existing user project preserved; choose a new name')
    results=[];project_settings=None
    for index,(track,hours,orbit_mode,gap_policy,weather_curve,weather) in enumerate(prepared,1):
        from scripts.blender_support.roundtrip import progress
        progress('创建镜头场景',index-1,len(prepared),track.get('name',''))
        keys=track.get('keyframeTrack',{}).get('keys',[])
        bpy.context.window.scene=template;template.frame_set(1)
        scene=template.copy();scene.name=f'导入{index:02d}｜'+track.get('name','网页分镜');scene.use_fake_user=True
        for collection in list(scene.collection.children):scene.collection.children.unlink(collection)
        for obj in list(scene.collection.objects):scene.collection.objects.unlink(obj)
        rig=bpy.data.collections.new('01｜网页运镜参数 · '+scene.name);effects=bpy.data.collections.new('03｜原生天气与大气 · '+scene.name)
        scene.collection.children.link(rig);scene.collection.children.link(effects)
        mapping={}
        for old in template.objects:
            new=old.copy()
            if old.type in ('CAMERA','MESH'):new.data=old.data.copy()
            (effects if old.get('earthstudio_layered_atmosphere') else rig).objects.link(new);mapping[old]=new
            if old.get('earthstudio_layered_atmosphere') or old.get('earthstudio_preview_proxy'):
                new.data.materials.clear();new.data.materials.append(old.data.materials[0].copy())
        for old,new in mapping.items():
            if old.parent in mapping:new.parent=mapping[old.parent]
            owners=[new,new.data if new.type=='CAMERA' else None]
            if old.get('earthstudio_layered_atmosphere') or old.get('earthstudio_preview_proxy'):owners.append(new.data.materials[0].node_tree)
            for owner in owners:
                if owner and owner.animation_data:
                    for curve in owner.animation_data.drivers:
                        for variable in curve.driver.variables:
                            for item in variable.targets:
                                if item.id in mapping:item.id=mapping[item.id]
            if old.get('earthstudio_layered_atmosphere') or old.get('earthstudio_preview_proxy'):
                for curve in new.data.materials[0].node_tree.animation_data.drivers:
                    if curve.data_path.endswith('.image_user.frame_offset'):
                        factor=60/native_manifest.get('step_minutes',10)
                        curve.driver.expression=gap_hold_expression(native_manifest['nodes'],native_manifest.get('step_minutes',10)*60,clock_start) if gap_policy=='hold-last-labeled' else f'min({len(native_manifest["nodes"])},max(1,floor((hours-{clock_start})*{factor!r}+1.00001)))-min(1000000,max(0,frame))'
        scene.camera=mapping[template.camera]
        first=track['samples'][0]
        scene.render.resolution_x,scene.render.resolution_y=first['width'],first['height']
        scene.render.resolution_percentage=100;scene.render.pixel_aspect_x=scene.render.pixel_aspect_y=1
        scene.render.fps=round(track['fps']);scene.render.fps_base=round(track['fps'])/track['fps']
        lens=next(c for c in scene.camera.data.animation_data.drivers if c.data_path=='lens')
        lens.driver.expression=f"36/(2*tan(fov*pi/360)*{first['aspect']!r})"
        control=mapping[bpy.data.objects[template.camera['earthstudio_controller']]];control.name='01｜运镜参数 · '+scene.name
        scene.camera['earthstudio_controller']=control.name;control.animation_data_clear()
        paths=json.loads(control['earthstudio_parameter_paths'])
        for parameter in (PARAMETERS if orbit_mode else ()):
            path=paths['["'+parameter+'"]']
            points=parameter_points(track['keyframeTrack']['keys'],parameter,track['keyframeTrack'],track['fps'])
            owner,attribute=path.rsplit('.',1)
            for point in points:
                setattr(control.path_resolve(owner),attribute,float(point['value']));control.keyframe_insert(path,frame=point['frame'])
            curve=next(c for c in curves(control) if c.data_path==path);curve.extrapolation='CONSTANT'
            for i,(key,point) in enumerate(zip(curve.keyframe_points,points)):
                key.interpolation='CONSTANT' if point['cut'] else 'BEZIER';key.handle_left_type=key.handle_right_type='FREE'
                before=(point['frame']-points[i-1]['frame'])/3 if i else 1/3
                after=(points[i+1]['frame']-point['frame'])/3 if i+1<len(points) else 1/3
                key.handle_left=(point['frame']-before,point['value']-before*point['left'])
                key.handle_right=(point['frame']+after,point['value']+after*point['right'])
        end=math.ceil(1+track['samples'][-1]['seconds']*track['fps'])
        path=paths['["weatherHours"]']
        from scripts.blender_support.weather_retime import apply as apply_weather
        apply_weather(control,path,hours[0],hours[1],track['samples'][-1]['seconds'],weather_curve,track['fps'])
        from scripts.blender_support.weather_fps import configure,apply_scene
        nodes=native_manifest['nodes'];interval=(__import__('datetime').datetime.fromisoformat(nodes[-1]['utc'].replace('Z','+00:00'))-__import__('datetime').datetime.fromisoformat(nodes[0]['utc'].replace('Z','+00:00'))).total_seconds()/max(1,len(nodes)-1) if len(nodes)>1 else 600
        if 'observationFps' in weather and abs(interval-weather['intervalSeconds'])>1e-6:raise ValueError('Observation cadence differs from delivered material')
        configure(scene,hours[0],hours[1],interval,weather.get('observationFps',min(120,max(.000001,(hours[1]-hours[0])*3600/interval/track['samples'][-1]['seconds']))))
        if 'observationFps' in weather:apply_scene(scene)
        if track.get('timelineProject',data.get('timelineProject',{})).get('sourcePlayback'):
            from scripts.blender_support.project_clock import configure as configure_project,apply_clock
            project_settings=configure_project(scene,track['fps'],project_settings)
            scene['earthstudio_weather_clock_mode']='sequence' if weather.get('projectClock') else 'mapped'
            if weather.get('projectClock'):apply_clock(scene)
        for key,default in [('blueAtmosphere',True),('nightAirglow',True),('newAirglow',False)]:
            owner,attribute=paths['["'+key+'"]'].rsplit('.',1)
            setattr(control.path_resolve(owner),attribute,bool(track.get('effects',{}).get(key,default)))
        for key,_,_,_,_ in CONTROLS[1:]:
            if key in track.get('effects',{}):
                owner,attribute=paths['["'+key+'"]'].rsplit('.',1)
                setattr(control.path_resolve(owner),attribute,float(track['effects'][key]))
        if not orbit_mode:
            free_camera(scene.camera,track)
            scene.camera.name='自由相机（直接编辑位置旋转与焦距） · '+scene.name
            control.name='天气与大气参数（自由相机另行编辑） · '+scene.name
            scene.camera['earthstudio_controller']=control.name
        scene['earthstudio_camera_edit_mode']='orbit_parameters' if orbit_mode else 'native_transform_lens_30fps'
        scene['weather_gap_display_policy']=gap_policy
        scene['weather_missing_nodes']=json.dumps([n for n in native_manifest['nodes'] if n['missing']])
        scene.frame_start,scene.frame_end=1,end;scene['earthstudio_scene_track']='WEB_'+str(index)
        scene['earthstudio_shot_duration_seconds']=track['samples'][-1]['seconds']
        control['earthstudio_editable_track']='WEB_'+str(index);scene.camera['earthstudio_editable_camera']='WEB_'+str(index)
        for marker in list(scene.timeline_markers):scene.timeline_markers.remove(marker)
        for key in keys:scene.timeline_markers.new('网页关键帧 '+str(key['time'])+'秒',frame=round(1+key['time']*track['fps']))
        # Copying a keying set can leave its owner pointing at the template.
        keyset=scene.keying_sets.active or scene.keying_sets.new(idname='WebCamera'+str(index),name='记录当前网页运镜 · 七项参数')
        keyset.paths.clear()
        if orbit_mode:
            for parameter in PARAMETERS:keyset.paths.add(control,paths['["'+parameter+'"]'])
        else:
            keyset.bl_label='记录自由相机 · 位置旋转焦距'
            keyset.paths.add(scene.camera,'location');keyset.paths.add(scene.camera,'rotation_quaternion');keyset.paths.add(scene.camera.data,'lens')
        scene.keying_sets.active_index=0
        selected=control if orbit_mode else scene.camera
        bpy.context.window.scene=scene;scene.frame_set(1);scene.view_layers[0].objects.active=selected
        for obj in scene.view_layers[0].objects:obj.select_set(obj==selected)
        scene.render.filepath='//renders/web_'+str(index)+'/frame_'
        results.append(dict(scene=scene.name,track=track.get('name'),weather_hours=hours,end_frame=end,edit_mode=scene['earthstudio_camera_edit_mode']))
    if template.get('layered_weather_sequence'):
        from scripts.blender_support.montage import create as create_montage
        name='00｜连续成片 · 导入分镜'
        suffix=1
        while name in bpy.data.scenes:
            suffix+=1;name='00｜连续成片 · 导入分镜 '+str(suffix)
        clips=[]
        for result,(track,*_) in zip(results,prepared):
            clip=track.get('keyframeTrack',{}).get('clip')
            item=dict(scene=result['scene'])
            if clip:
                a,b=clip['inFrame'],clip['outFrame']
                if type(a) is not int or type(b) is not int or not 0<=a<b<=round(track['samples'][-1]['seconds']*track['fps']):raise ValueError('Invalid non-destructive clip bounds')
                item.update({'in':a+1,'out':b})
            clips.append(item)
        montage,edit=create_montage(clips,name=name)
        bpy.context.window.scene=bpy.data.scenes[results[0]['scene']]
    else:bpy.context.window.scene=bpy.data.scenes[results[0]['scene']]
    # A multi-megabyte single line makes Blender's text insertion very slow.
    # Keep the complete export readable, with bounded lines per sample/value.
    bpy.data.texts.new('网页相机原始导出.json').write(json.dumps(data,ensure_ascii=False,indent=2))
    from scripts.blender_support.roundtrip import finalize,progress
    if template.get('layered_weather_sequence'):finalize(data,results,target,free_camera)
    target.parent.mkdir(parents=True,exist_ok=True)
    progress('保存Blender工程',0,1,str(target))
    bpy.ops.wm.save_as_mainfile(filepath=str(target),relative_remap=True)
    target.with_suffix('.import.json').write_text(json.dumps(dict(project=str(target),scenes=results),ensure_ascii=False,indent=2),encoding='utf-8')
    print('WEB_CAMERAS_AND_NATIVE_WEATHER_IMPORTED',target,flush=True)
    progress('完成',1,1,str(target))

if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:];source=Path(args[0]).resolve()
    target=Path(args[1]).resolve() if len(args)>1 else Path(bpy.data.filepath).parent/'user_projects'/(source.stem+'_Blender.blend')
    if '--update' in args:
        from scripts.blender_support.roundtrip import update_bundle
        update_bundle(json.loads(source.read_text(encoding='utf-8-sig')),target,free_camera)
    else:import_bundle(source,target)
