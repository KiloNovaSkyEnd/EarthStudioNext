"""Editable ground contribution; compose encoded components before exact sRGB EOTF."""
from pathlib import Path
import json


def value(n, control, key, default):
    if control is None: return default
    if key not in control: control[key]=default
    node=n.node('ShaderNodeValue');node.label=key
    driver=node.outputs[0].driver_add('default_value').driver
    variable=driver.variables.new();variable.name='v'
    paths=json.loads(control.get('earthstudio_parameter_paths','{}'))
    variable.targets[0].id=control;variable.targets[0].data_path=paths.get('["'+key+'"]','["'+key+'"]')
    driver.expression='v'
    return node.outputs[0]


def linear(n, encoded):
    channels=[]
    for component in n.xyz(encoded):
        component=n.m('MINIMUM',1,n.m('MAXIMUM',0,component))
        low=n.m('DIVIDE',component,12.92)
        high=n.m('POWER',n.m('DIVIDE',n.m('ADD',component,.055),1.055),2.4)
        use_high=n.m('GREATER_THAN',component,.04045)
        channels.append(n.m('ADD',n.m('MULTIPLY',low,n.m('SUBTRACT',1,use_high)),n.m('MULTIPLY',high,use_high)))
    return n.combine(channels)


def color(n, gx, gy, visible, master, assets):
    import bpy
    layers=master['production_layers']
    control=bpy.data.objects.get(master.get('production_control',''))
    left,bottom,right,top=master['extent']
    uv=n.combine((n.m('DIVIDE',n.m('SUBTRACT',gx,left),right-left),
                  n.m('DIVIDE',n.m('SUBTRACT',gy,bottom),top-bottom),0))
    def texture(role):
        item=next(a for a in layers if a['role']==role)
        image=bpy.data.images.load(str(Path(assets)/item['path']),check_existing=True)
        # Shared SEQUENCE datablocks can temporarily point at an unevaluated frame
        # while another scene is being built. Physical files were verified by the packager.
        if image.source!='SEQUENCE' and list(image.size)[::-1]!=item['shape']:
            raise ValueError(f'Layer dimensions differ: {item["path"]}: {list(image.size)} != {item["shape"]}')
        image.colorspace_settings.name='Non-Color'
        node=n.node('ShaderNodeTexImage');node.image=image
        node.interpolation='Linear';node.extension='CLIP';node.label=role
        temporal=master.get('production_sequence')
        if temporal and temporal['count']>1 and not item.get('static'):
            image.source='SEQUENCE'
            user=node.image_user;user.frame_start=1;user.frame_duration=1000000;user.use_auto_refresh=True
            driver=user.driver_add('frame_offset').driver
            variable=driver.variables.new();variable.name='hours';variable.targets[0].id=control
            variable.targets[0].data_path=json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
            start,end=temporal['clock_start'],temporal['clock_end'];count=temporal['count']
            driver.expression=f'min({count},max(1,floor((hours-{start!r})/{(end-start)!r}*{count-1}+1.00001)))-min(1000000,max(0,frame))'
        n.put(uv,node.inputs['Vector'])
        return node.outputs['Color']
    base=texture('stock-clouds-day-without-ground-background')
    night=texture('shared-static-night-background')
    transmission=n.xyz(texture('stock-ground-transmission'))[0]
    support=n.xyz(texture('actual-observation-support'))[0]
    hsv=n.node('ShaderNodeHueSaturation');hsv.label='地面夜景 · 独立调色'
    n.put(night,hsv.inputs['Color'])
    n.put(n.m('ADD',.5,n.m('DIVIDE',value(n,control,'groundHue',0),360)),hsv.inputs['Hue'])
    n.put(value(n,control,'groundSaturation',1),hsv.inputs['Saturation'])
    tint=n.combine(tuple(value(n,control,'groundTint'+c,1) for c in 'RGB'))
    strength=n.m('MULTIPLY',value(n,control,'groundEnabled',1),value(n,control,'groundBrightness',1))
    ground=n.v('SCALE',n.v('MULTIPLY',hsv.outputs['Color'],tint),n.m('MULTIPLY',transmission,strength))
    result=linear(n,n.v('ADD',base,ground))
    valid=n.m('MULTIPLY',visible,support)
    return n.v('ADD',n.v('SCALE',result,valid),n.v('SCALE',(.008,.008,.008),n.m('SUBTRACT',1,valid)))


def configure(control):
    defaults={'groundEnabled':(1,0,1),'groundBrightness':(1,0,4),'groundHue':(0,-180,180),
              'groundSaturation':(1,0,2),**{'groundTint'+c:(1,0,2) for c in 'RGB'}}
    labels={'groundEnabled':'地面夜景开关','groundBrightness':'地面夜景亮度','groundHue':'地面夜景色相（度）',
            'groundSaturation':'地面夜景饱和度','groundTintR':'地面夜景红色','groundTintG':'地面夜景绿色','groundTintB':'地面夜景蓝色'}
    modifier=control.modifiers[0];group=modifier.node_group
    inputs=next(node for node in group.nodes if node.bl_idname=='NodeGroupInput')
    scale=next(node for node in group.nodes if node.bl_idname=='ShaderNodeMath' and node.operation=='MULTIPLY' and abs(node.inputs[1].default_value-1e-8)<1e-12)
    total=scale.inputs[0].links[0].from_socket
    paths=json.loads(control['earthstudio_parameter_paths'])
    for key,(default,minimum,maximum) in defaults.items():
        control[key]=default
        control.id_properties_ui(key).update(min=minimum,max=maximum,default=default,
            description='独立地面夜景；不影响云图、蓝色大气或夜间气辉')
        if '["'+key+'"]' in paths: continue
        socket=group.interface.new_socket(name=labels[key],in_out='INPUT',socket_type='NodeSocketBool' if key=='groundEnabled' else 'NodeSocketFloat')
        socket.default_value=bool(default) if key=='groundEnabled' else float(default)
        if key!='groundEnabled': socket.min_value=minimum;socket.max_value=maximum
        getattr(modifier.properties.inputs,socket.identifier).value=socket.default_value
        paths['["'+key+'"]']=f'modifiers["{modifier.name}"].properties.inputs.{socket.identifier}.value'
        add=group.nodes.new('ShaderNodeMath');add.operation='ADD'
        group.links.new(total,add.inputs[0]);group.links.new(inputs.outputs[socket.name],add.inputs[1]);total=add.outputs[0]
    group.links.new(total,scale.inputs[0])
    control['earthstudio_parameter_paths']=json.dumps(paths)
