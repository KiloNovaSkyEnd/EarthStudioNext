"""Independent accepted R3 emission with project-bound Sun and retained legacy blue/glow."""
import json,inspect
from . import layered_atmosphere as legacy
from .airglow_transport_nodes import group,ray_inputs

CONTROLS=[('newAirglow','新版气辉开关',False,0,1),
    ('newGlowDensity','新版气辉浓度',1.,0.,2.5),('newGlowThickness','新版气辉厚度',1.,.5,2.),
    ('newGlowHue','新版气辉色相（度）',0.,-180.,180.),('newGlowSaturation','新版气辉饱和度',1.,0.,2.),
    ('newGlowBrightness','新版气辉亮度',1.,0.,3.)]
NODE_TEMPLATE_SHA256='de84719edef02d300e349e8c374a007c89b06f822f18d12bc565c00a2a90e3a7'
_shared=None
_original_create=legacy.create
def controls(control,paths):
    modifier=control.modifiers[0];tree=modifier.node_group
    inputs=next(n for n in tree.nodes if n.bl_idname=='NodeGroupInput')
    scale=next(n for n in tree.nodes if n.bl_idname=='ShaderNodeMath' and n.operation=='MULTIPLY' and abs(n.inputs[1].default_value-1e-8)<1e-12)
    total=scale.inputs[0].links[0].from_socket
    for key,label,default,lo,hi in CONTROLS:
        if '["'+key+'"]' in paths:continue
        socket=tree.interface.new_socket(name=label,in_out='INPUT',socket_type='NodeSocketBool' if key=='newAirglow' else 'NodeSocketFloat')
        socket.default_value=default
        if key!='newAirglow':socket.min_value=lo;socket.max_value=hi
        getattr(modifier.properties.inputs,socket.identifier).value=default
        paths['["'+key+'"]']=f'modifiers["{modifier.name}"].properties.inputs.{socket.identifier}.value'
        add=tree.nodes.new('ShaderNodeMath');add.operation='ADD';tree.links.new(total,add.inputs[0]);tree.links.new(inputs.outputs[socket.name],add.inputs[1]);total=add.outputs[0]
    tree.links.new(total,scale.inputs[0]);control['earthstudio_parameter_paths']=json.dumps(paths)

def add_emission(n,sun,result,control,paths):
    global _shared
    import bpy
    try:
        valid=_shared is not None and _shared.name in bpy.data.node_groups
    except ReferenceError:
        valid=False
    if not valid:
        from pathlib import Path
        import hashlib
        resource=Path(__file__).resolve().parents[2]/'resources/blender/dual_airglow_r3.blend'
        if hashlib.sha256(resource.read_bytes()).hexdigest()!=NODE_TEMPLATE_SHA256:raise ValueError('Airglow node template fingerprint differs')
        with bpy.data.libraries.load(str(resource),link=False) as (source,target):
            matches=[name for name in source.node_groups if name.startswith('Research R3')]
            if len(matches)!=1:raise ValueError('Airglow node template is ambiguous')
            target.node_groups=matches
        _shared=target.node_groups[0]
    get=lambda key:legacy.object_value(n,control,paths['["'+key+'"]'],key)
    radiance,first=ray_inputs(n,_shared,sun,get('newGlowDensity'),get('newGlowThickness'))
    hsv=n.node('ShaderNodeHueSaturation');hsv.label='新版气辉 · 独立颜色调整'
    n.put(radiance,hsv.inputs['Color']);n.put(n.m('ADD',.5,n.m('DIVIDE',get('newGlowHue'),360.)),hsv.inputs['Hue'])
    n.put(get('newGlowSaturation'),hsv.inputs['Saturation']);n.put(get('newGlowBrightness'),hsv.inputs['Value'])
    return n.v('ADD',result,n.v('SCALE',hsv.outputs[0],n.m('MULTIPLY',get('newAirglow'),first)))

def create(scene,master,assets,images,sun,control,paths):
    controls(control,paths)
    # Reuse the legacy node construction verbatim: inject ONLY the independent addition.
    source=inspect.getsource(_original_create)
    needle="    emission = n.node('ShaderNodeEmission')"
    if source.count(needle)!=1:raise ValueError('Legacy shader changed; dual glow qualification required')
    source=source.replace(needle,'    result = _add_emission(n,sun,result,control,paths)\n'+needle)
    scope=dict(legacy.__dict__);scope['_add_emission']=add_emission
    exec(compile(source,__file__,'exec'),scope)
    obj=scope['create'](scene,master,assets,images,sun,control,paths)
    obj.data.materials[0]['earthstudio_dual_airglow']='r3-v1'
    obj.data=obj.data.copy();factor=(6371.+500.)/(6371.+256.)
    for vertex in obj.data.vertices:vertex.co*=factor
    scene['earthstudio_atmosphere_profile']='dual-independent-r3-v1'
    return obj

def upgrade_all():
    """Append the independent glow; preserve existing artist nodes and Sun links."""
    import bpy
    from .shader_math import Nodes
    upgraded=[]
    for scene in bpy.data.scenes:
        if not scene.camera or 'earthstudio_controller' not in scene.camera:continue
        control=bpy.data.objects[scene.camera['earthstudio_controller']]
        paths=json.loads(control['earthstudio_parameter_paths'])
        had_dual=all('["'+key+'"]' in paths for key,_,_,_,_ in CONTROLS)
        controls(control,paths)
        for obj in scene.objects:
            if not obj.get('earthstudio_layered_atmosphere'):continue
            material=obj.data.materials[0]
            if material.get('earthstudio_dual_airglow'):continue
            existing=any(n.bl_idname=='ShaderNodeGroup' and n.node_tree and n.node_tree.name.startswith('Research R3') for n in material.node_tree.nodes)
            if existing:
                if not had_dual:raise ValueError('Existing research glow needs explicit migration; original preserved')
                material['earthstudio_dual_airglow']='r3-v1';continue
            obj.data=obj.data.copy();material=material.copy();obj.data.materials[0]=material;tree=material.node_tree
            outputs=[n for n in tree.nodes if n.bl_idname=='ShaderNodeOutputMaterial' and n.is_active_output]
            if len(outputs)!=1 or not outputs[0].inputs['Surface'].is_linked:raise ValueError('Unsupported artist surface; original preserved')
            emission=outputs[0].inputs['Surface'].links[0].from_node
            if emission.bl_idname!='ShaderNodeEmission':raise ValueError('Unsupported artist emission; original preserved')
            solar=[]
            for node in tree.nodes:
                if node.bl_idname!='ShaderNodeMath' or node.operation!='ADD':continue
                if not any(not i.is_linked and abs(i.default_value-.104528)<1e-6 for i in node.inputs):continue
                for inp in node.inputs:
                    if inp.is_linked:
                        dot=inp.links[0].from_node
                        if dot.bl_idname=='ShaderNodeVectorMath' and dot.operation=='DOT_PRODUCT':solar.append(dot.inputs[1])
            if len(solar)!=1:raise ValueError('Cannot uniquely identify project Sun; original preserved')
            sun=solar[0].links[0].from_socket if solar[0].is_linked else tuple(solar[0].default_value)
            old=emission.inputs['Color'];result=old.links[0].from_socket if old.is_linked else tuple(old.default_value[:3])
            n=object.__new__(Nodes);n.tree=tree;n.put(add_emission(n,sun,result,control,paths),emission.inputs['Color'])
            for vertex in obj.data.vertices:vertex.co*=(6371.+500.)/(6371.+256.)
            material['earthstudio_dual_airglow']='r3-v1'
        scene['earthstudio_atmosphere_profile']='dual-independent-r3-v1';upgraded.append(scene.name)
    return upgraded
