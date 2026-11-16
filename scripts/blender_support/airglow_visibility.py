"""Repair the obsolete front-face gate on opaque analytical R3 proxies only."""
import bpy

VERSION='opaque-ray-v2'

def repair_material(material):
    tree=material.node_tree
    if not tree or material.get('earthstudio_airglow_visibility')==VERSION:return 0
    # Removing a surface-count gate is valid only for the opaque analytical
    # emission output. A custom transparent/volume material needs separate care.
    outputs=[n for n in tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output]
    if len(outputs)!=1 or not outputs[0].inputs['Surface'].is_linked:return 0
    if outputs[0].inputs['Surface'].links[0].from_node.type!='EMISSION':return 0
    hsv=next((n for n in tree.nodes if n.type=='HUE_SAT' and n.label=='新版气辉 · 独立颜色调整'),None)
    if not hsv:return 0
    changed=0
    for link in list(hsv.outputs['Color'].links):
        scale=link.to_node
        if scale.type!='VECT_MATH' or scale.operation!='SCALE':continue
        if not scale.inputs['Scale'].is_linked:continue
        gate=scale.inputs['Scale'].links[0].from_node
        if gate.type!='MATH' or gate.operation!='MULTIPLY':continue
        toggle=[i for i in gate.inputs[:2] if i.is_linked and i.links[0].from_node.type=='VALUE' and i.links[0].from_node.label=='newAirglow']
        if len(toggle)!=1:continue
        face=gate.inputs[1] if toggle[0]==gate.inputs[0] else gate.inputs[0]
        if not face.is_linked and face.default_value==1.:continue
        if not face.is_linked:continue
        old=face.links[0].from_node
        if old.type!='MATH' or old.operation!='MAXIMUM':continue
        branches=[i.links[0].from_node for i in old.inputs[:2] if i.is_linked]
        if len(branches)!=2 or {n.operation for n in branches if n.type=='MATH'}!={'SUBTRACT','LESS_THAN'}:continue
        subtract=next(n for n in branches if n.operation=='SUBTRACT')
        inside=next(n for n in branches if n.operation=='LESS_THAN')
        if subtract.inputs[0].is_linked or subtract.inputs[0].default_value!=1.:continue
        if not subtract.inputs[1].is_linked or subtract.inputs[1].links[0].from_socket.name!='Backfacing':continue
        if inside.inputs[1].is_linked or abs(inside.inputs[1].default_value-6871.)>.01:continue
        tree.links.remove(face.links[0]);face.default_value=1.;changed+=1
    if changed:material['earthstudio_airglow_visibility']=VERSION;tree.update_tag()
    return changed

def repair_all():
    seen=set();changed=0
    for obj in bpy.data.objects:
        if not obj.get('earthstudio_layered_atmosphere'):continue
        for material in obj.data.materials:
            if not material or material.as_pointer() in seen:continue
            seen.add(material.as_pointer());changed+=repair_material(material)
    return changed
