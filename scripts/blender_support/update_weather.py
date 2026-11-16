"""Retarget only owned weather image/clock drivers. Keep artist camera/effect edits."""
import json
from pathlib import Path
import bpy
from ges_next.production.assets import verify_assets
from scripts.blender_support.editable_camera import curves
from ges_next.layered_sequence.collection import ROLES


def update(root):
    root=Path(root).resolve();sequence=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'))
    master=json.loads((root/'native_master.json').read_text(encoding='utf-8'))
    verify_assets(root,sequence['files']+sequence['auxiliary_files'])
    count=len(sequence['nodes']);end=master['production_sequence']['clock_end'];updated=[]
    roles={r[0] for r in ROLES.values()}
    checked=set()
    for scene in bpy.data.scenes:
        if not scene.get('layered_weather_sequence'):continue
        if scene['weather_start_utc']!=sequence['nodes'][0]['utc'] or scene['weather_end_utc']>=sequence['nodes'][-1]['utc']:
            raise ValueError('Weather update must extend the same sequence origin')
        control=bpy.data.objects[scene.camera['earthstudio_controller']]
        for obj in scene.objects:
            if not obj.get('earthstudio_layered_atmosphere') or obj.get('earthstudio_preview_proxy'):continue
            for node in obj.data.materials[0].node_tree.nodes:
                if node.type=='TEX_IMAGE' and node.label=='stock-clouds-day-without-ground-background':
                    old_root=Path(bpy.path.abspath(node.image.filepath)).resolve().parents[2]
                    if old_root not in checked:
                        from ges_next.layered_sequence.prefix import verify_prefix
                        verify_prefix(old_root,root);checked.add(old_root)
        paths=json.loads(control['earthstudio_parameter_paths']);clock=paths['["weatherHours"]']
        changed=0
        for obj in scene.objects:
            if not obj.get('earthstudio_layered_atmosphere'):continue
            items=master['preview_layers'] if obj.get('earthstudio_preview_proxy') else master['production_layers']
            for material in obj.data.materials:
                for node in material.node_tree.nodes:
                    if node.type!='TEX_IMAGE' or node.label not in roles:continue
                    item=next(a for a in items if a['role']==node.label)
                    node.image=bpy.data.images.load(str(root/item['path']),check_existing=True)
                    node.image.colorspace_settings.name='Non-Color'
                    if item.get('static'):
                        node.image.source='FILE'
                        try:node.image_user.driver_remove('frame_offset')
                        except TypeError:pass
                    else:
                        node.image.source='SEQUENCE';user=node.image_user
                        user.frame_start=1;user.frame_duration=1000000;user.use_auto_refresh=True
                        driver=user.driver_add('frame_offset').driver
                        if not driver.variables:
                            var=driver.variables.new();var.name='hours';var.targets[0].id=control;var.targets[0].data_path=clock
                        driver.expression=f'min({count},max(1,floor(hours/{end!r}*{count-1}+1.00001)))-min(1000000,max(0,frame))'
                    changed+=1
            # Sun curve follows the same absolute elapsed hours, with an expanded domain.
            material=obj.data.materials[0]
            for node in material.node_tree.nodes:
                if node.type=='MATH' and node.operation=='DIVIDE' and node.inputs[0].is_linked:
                    source=node.inputs[0].links[0].from_node
                    if source.type=='MATH' and source.operation=='SUBTRACT' and source.inputs[0].is_linked:
                        value=source.inputs[0].links[0].from_node
                        if value.type=='VALUE' and value.label=='天气时间 UTC−7':node.inputs[1].default_value=end
                if node.type=='CURVE_FLOAT' and node.label.startswith('UTC太阳方向 '):
                    axis=int(node.label.rsplit(' ',1)[1]);points=node.mapping.curves[0].points
                    for point in list(points)[1:-1]:points.remove(point)
                    points[0].location=(0,sequence['suns'][0][axis]);points[-1].location=(1,sequence['suns'][-1][axis])
                    for i,vector in enumerate(sequence['suns'][1:-1],1):points.new(i/(count-1),vector[axis])
                    for point in points:point.handle_type='VECTOR'
                    node.mapping.update()
        owner,attribute=clock.rsplit('.',1)
        for socket in control.modifiers[0].node_group.interface.items_tree:
            if getattr(socket,'identifier',None)==owner.rsplit('.',1)[-1]:socket.max_value=end
        # Keep every existing weather/camera/effect keyframe and scene duration.
        # The newly available hours can be used by extending the weather curve manually.
        scene['weather_end_utc']=sequence['nodes'][-1]['utc']
        if scene.get('earthstudio_project_clock'):scene['earthstudio_weather_end']=end
        if changed!=8:raise ValueError('需要完整的正式/预览四图层；自定义改造后的材质请单独核对，未保存更新副本')
        scene['earthstudio_material_root']=str(root)
        scene['weather_available_hours']=end
        scene['weather_update_note']=('项目源图时钟继续按统一帧率播放；原相机与场景时长保持，新增观测已接入。' if scene.get('earthstudio_project_clock') else
            '原镜头/天气曲线及时间长度保持；新增观测已可用，可延长天气曲线或增加分镜。')
        updated.append(dict(scene=scene.name,texture_nodes=changed))
    if not updated:raise ValueError('No compatible layered weather scenes in this file')
    return updated
