"""Blender --background --python THIS -- camera-or-bundle.json output.blend.
Editable WGS84 parameter rigs plus baked comparison cameras.
Weather materials are not included by this importer.
"""
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.camera import validate,basis,horizontal_lens_mm
from ges_next.isolation import require_writable
from scripts.blender_support.editable_camera import create as editable_rig


def import_track(scene,track,name):
    import bpy
    from mathutils import Matrix
    data=bpy.data.cameras.new(name);camera=bpy.data.objects.new(name,data)
    scene.collection.objects.link(camera)
    camera.rotation_mode='QUATERNION';data.sensor_fit='HORIZONTAL';data.sensor_width=36
    data.clip_start=.00001;data.clip_end=1000
    previous=None
    for sample in track['samples']:
        frame=1+sample['seconds']*track['fps']
        camera.location=[v/1e6 for v in sample['position']]
        q=Matrix(basis(sample['direction'],sample['up'])).transposed().to_quaternion()
        if previous is not None and q.dot(previous)<0:q.negate()
        previous=q.copy();camera.rotation_quaternion=q;data.lens=horizontal_lens_mm(sample)
        camera.keyframe_insert('location',frame=frame);camera.keyframe_insert('rotation_quaternion',frame=frame)
        data.keyframe_insert('lens',frame=frame)
    cut_frames=[1+track['samples'][i-1]['seconds']*track['fps'] for i in range(1,len(track['samples'])) if track['samples'][i].get('cut')]
    for owner in [camera,data]:
        action=owner.animation_data.action
        curves=action.fcurves if hasattr(action,'fcurves') else [curve for layer in action.layers for strip in layer.strips for bag in strip.channelbags for curve in bag.fcurves]
        for curve in curves:
            for point in curve.keyframe_points:point.interpolation='CONSTANT' if any(abs(point.co.x-f)<.001 for f in cut_frames) else 'LINEAR'
    camera['earthstudio_take_name']=name
    camera['earthstudio_duration_seconds']=track['samples'][-1]['seconds']
    camera['earthstudio_weather_interval']=json.dumps(track.get('timelineProject',{}).get('weather'))
    plan=track.get('shotPlan');keys=track.get('keyframeTrack',{}).get('keys')
    if keys or plan:
        references=bpy.data.collections.new('Cesium reference shots' if plan else name+' keyframe references')
        scene.collection.children.link(references)
        items=[]
        if keys:
            items=[(key['time'],key['pose'],name+' @ '+str(round(key['time'],3))+'s') for key in keys]
        else:
            elapsed=0
            for index,shot in enumerate(plan['shots']):
                if index:elapsed+=shot['duration']
                items.append((elapsed,shot['pose'],shot['name']))
        for seconds,pose,label in items:
            ref_data=bpy.data.cameras.new(label);ref=bpy.data.objects.new(label,ref_data);references.objects.link(ref)
            ref.location=[v/1e6 for v in pose['position']];ref.rotation_mode='QUATERNION'
            ref.rotation_quaternion=Matrix(basis(pose['direction'],pose['up'])).transposed().to_quaternion()
            ref_data.sensor_fit='HORIZONTAL';ref_data.sensor_width=36;ref_data.lens=horizontal_lens_mm(pose)
            ref_data.clip_start=.00001;ref_data.clip_end=1000
            ref['reference_only']='Editable reference pose; editing does not auto-rebake the main camera'
            scene.timeline_markers.new(label,frame=round(1+seconds*track['fps']))
    source=bpy.data.texts.new(name+' source.json');source.write(json.dumps(track,ensure_ascii=False,indent=2))
    return camera


def main():
    import bpy
    args=sys.argv[sys.argv.index('--')+1:]
    if len(args)!=2:raise ValueError('Expected camera JSON and output .blend')
    payload=json.loads(Path(args[0]).read_text(encoding='utf-8'))
    tracks=payload.get('tracks') if payload.get('schema')=='earthstudio.camera_bundle.v1' else [payload]
    if not isinstance(tracks,list) or not 1<=len(tracks)<=50:raise ValueError('Expected 1–50 camera tracks')
    tracks=[validate(t) for t in tracks]
    first=tracks[0];frame=first['samples'][0]
    if any(t['fps']!=first['fps'] or t['samples'][0]['width']!=frame['width'] or t['samples'][0]['height']!=frame['height'] for t in tracks):raise ValueError('Camera tracks require matching frame format')
    output=require_writable(args[1]);output.parent.mkdir(parents=True,exist_ok=True)
    scene=bpy.context.scene;scene.render.fps=first['fps'];scene.render.resolution_percentage=100
    scene.render.resolution_x=frame['width'];scene.render.resolution_y=frame['height']
    scene.render.pixel_aspect_x=scene.render.pixel_aspect_y=1
    cameras=[import_track(scene,t,t.get('name','Cesium camera') if len(tracks)>1 or t.get('name') else 'Cesium camera') for t in tracks]
    editable=[editable_rig(scene,t,c) for t,c in zip(tracks,cameras)]
    active=payload.get('timelineProject',{}).get('activeTrack')
    selected=next((i for i,t in enumerate(tracks) if t.get('keyframeTrack',{}).get('id')==active),0)
    scene.camera=editable[selected] or cameras[selected]
    scene.frame_start=1;scene.frame_end=max(1,max(math.ceil(1+t['samples'][-1]['seconds']*t['fps']) for t in tracks))
    scene['earthstudio_earth_model']='WGS84 ECEF; 1 Blender unit = 1000000 metres'
    scene['earthstudio_ellipsoid_radii_units']=[6.378137,6.378137,6.356752314245]
    scene['earthstudio_camera_only']=True;scene['earthstudio_camera_tracks']=len(cameras)
    scene['earthstudio_editable_rigs']=sum(c is not None for c in editable)
    instructions=bpy.data.texts.new('START_HERE · 运镜编辑.txt')
    instructions.write('''这是相机编辑测试工程，尚未包含卫星天气材质和大气。\n
每个分镜独立，共享天气时段不等于共用相机动画。\n
1. 在 Outliner 展开分镜的“可编辑运镜”集合，选择“参数控制器”。\n
2. 在物体属性 → 自定义属性修改 targetLon/targetLat（目标经纬度）、heading（绕目标）、pitch（俯看）、rangeKm（距离）、roll（画面旋转）、fov（垂直画角）。\n
3. 动画参数改值后，在属性上按 I 插入关键帧；也可在 Graph Editor 修改值及曲线。只改当前值而不插帧，换帧后会回到动画值。\n
4. Graph Editor 中的稀疏参数曲线已包含原速度曲线的控制点；移动控制点或手柄可继续修改。\n
5. 修改片段时长：选中该控制器全部曲线，绕第1帧缩放关键帧的时间；再修改场景结束帧。其他控制器不会被一起缩放。\n
6. 在场景相机栏切换各分镜的“可编辑相机”，分别渲染。每条分镜的时长保存在相机自定义属性中；场景结束帧初始为最长分镜。\n
7. 原始逐帧相机保留作比较，修改参数控制器不会改写比较相机。自由姿态或混合轨道当前只提供逐帧相机，不伪装成绕目标参数。\n
8. 使用原生驱动器，无需开启自动运行 Python；源工程 JSON 也保存在文本数据块中。\n
地球坐标为 WGS84 ECEF，1 Blender 单位 = 1000000 米。\n''')
    project=payload.get('timelineProject')
    if project:
        text=bpy.data.texts.new('earthstudio_timeline_project.json');text.write(json.dumps(project,ensure_ascii=False,indent=2))
    scene.frame_set(1);bpy.ops.wm.save_as_mainfile(filepath=str(output))


if __name__=='__main__':main()
