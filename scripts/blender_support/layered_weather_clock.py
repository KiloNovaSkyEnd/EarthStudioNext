"""Native modifier weather clock; no Python frame-change handler required."""
import json


def attach(control,scene,start,end):
    group=control.modifiers[0].node_group;modifier=control.modifiers[0]
    paths=json.loads(control['earthstudio_parameter_paths'])
    if '["weatherHours"]' not in paths:
        socket=group.interface.new_socket(name='天气时间（从素材起点起算小时）',in_out='INPUT',socket_type='NodeSocketFloat')
        socket.min_value,socket.max_value,socket.default_value=start,end,start
        socket.description=f'{start}代表素材起点；可输入、插帧或改曲线。缺档显示灰色。'
        path=f'modifiers["{modifier.name}"].properties.inputs.{socket.identifier}.value'
        paths['["weatherHours"]']=path
        inputs=next(n for n in group.nodes if n.bl_idname=='NodeGroupInput')
        scale=next(n for n in group.nodes if n.bl_idname=='ShaderNodeMath' and n.operation=='MULTIPLY' and abs(n.inputs[1].default_value-1e-8)<1e-12)
        add=group.nodes.new('ShaderNodeMath');add.operation='ADD'
        group.links.new(scale.inputs[0].links[0].from_socket,add.inputs[0]);group.links.new(inputs.outputs[socket.name],add.inputs[1]);group.links.new(add.outputs[0],scale.inputs[0])
        control['earthstudio_parameter_paths']=json.dumps(paths)
    path=paths['["weatherHours"]'];owner,attribute=path.rsplit('.',1)
    for socket in group.interface.items_tree:
        if getattr(socket,'identifier',None)==owner.rsplit('.',1)[-1]:
            socket.name='天气经过（小时，从素材起点=0）';socket.min_value=start;socket.max_value=end;socket.default_value=start
            socket.description='相机时长与天气时钟独立。真实UTC可见时间标记；可输入、插帧或调曲线。'
    # Only replace this clock, preserving independent camera/effect actions.
    from scripts.blender_support.editable_camera import curves
    for curve in curves(control):
        if curve.data_path==path:curve.keyframe_points.clear()
    for frame,value in [(scene.frame_start,start),(scene.frame_end,end)]:
        setattr(control.path_resolve(owner),attribute,float(value));control.keyframe_insert(data_path=path,frame=frame)
    for curve in curves(control):
        if curve.data_path==path:
            for point in curve.keyframe_points:point.interpolation='LINEAR'
    return paths
