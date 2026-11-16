"""One native viewport-quality control for shared-look shot scenes.

Safe to apply to an open artist project: only preview bindings/UI change.
Camera, weather, materials, render visibility and artistic values are retained.
"""
import json,re
import bpy

def resolve(scene):
    camera=scene.camera
    local=bpy.data.objects.get(camera.get('earthstudio_controller','')) if camera else None
    shared=bpy.data.objects.get(scene.get('earthstudio_shared_look',''))
    for obj in (shared,local):
        if obj and 'earthstudio_parameter_paths' in obj:
            path=json.loads(obj['earthstudio_parameter_paths']).get('["previewHigh"]')
            if path:return obj,path
    return None

def bind(scene):
    shared=bpy.data.objects.get(scene.get('earthstudio_shared_look',''))
    camera=scene.camera
    local=bpy.data.objects.get(camera.get('earthstudio_controller','')) if camera else None
    if not shared or not local or shared==local:return 0
    resolved=resolve(scene)
    if not resolved:return 0
    owner,path=resolved
    local_path=json.loads(local['earthstudio_parameter_paths']).get('["previewHigh"]')
    changed=0
    for obj in scene.objects:
        if not (obj.get('earthstudio_layered_atmosphere') or obj.get('earthstudio_preview_proxy')):continue
        if not obj.animation_data:continue
        for curve in obj.animation_data.drivers:
            if curve.data_path!='hide_viewport':continue
            for variable in curve.driver.variables:
                for target in variable.targets:
                    if target.id in (local,shared) and target.data_path in (local_path,path):
                        if target.id!=owner or target.data_path!=path:
                            target.id=owner;target.data_path=path;changed+=1
        obj.update_tag()
    # Keep the operative switch visible on the shared object. Hide its obsolete
    # local duplicate, without changing interfaces used by non-shared templates.
    match=re.search(r'inputs\.([^.]+)\.value',local_path or '')
    if match:
        for modifier in local.modifiers:
            if modifier.type!='NODES' or not modifier.node_group:continue
            group=modifier.node_group
            socket=next((s for s in group.interface.items_tree if s.identifier==match.group(1)),None)
            if socket and not socket.hide_in_modifier:
                values={p:local.path_resolve(p) for p in json.loads(local['earthstudio_parameter_paths']).values()}
                modifier.node_group=group.copy()
                for p,value in values.items():
                    parent,attribute=p.rsplit('.',1);setattr(local.path_resolve(parent),attribute,value)
                socket=next(s for s in modifier.node_group.interface.items_tree if s.identifier==match.group(1))
                socket.hide_in_modifier=True
    scene['earthstudio_preview_control_version']=2
    return changed

def repair_all():
    return sum(bind(scene) for scene in bpy.data.scenes)
