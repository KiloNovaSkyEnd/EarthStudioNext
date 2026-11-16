"""Comparable native editing state, excluding weather image and solar driver plumbing."""
from scripts.blender_support.editable_camera import curves


def animation(owner):
    if not getattr(owner,'animation_data',None) or not owner.animation_data.action:return []
    return [dict(path=c.data_path,index=c.array_index,extrapolation=c.extrapolation,
        keys=[dict(co=list(p.co),left=list(p.handle_left),right=list(p.handle_right),
            left_type=p.handle_left_type,right_type=p.handle_right_type,interpolation=p.interpolation) for p in c.keyframe_points]) for c in curves(owner)]


def snapshot():
    import bpy
    return dict(objects={o.name:dict(location=list(o.location),rotation=list(o.rotation_euler),quaternion=list(o.rotation_quaternion),
        scale=list(o.scale),action=animation(o),data_action=animation(o.data) if o.data else [],
        lens=o.data.lens if o.type=='CAMERA' else None,
        effects={k:o[k] for k in o.keys() if k.startswith(('ground','blue','warm','nightAirglow')) and isinstance(o[k],(int,float,bool))})
        for o in bpy.data.objects if not o.get('earthstudio_layered_atmosphere')},
        scenes={s.name:dict(start=s.frame_start,end=s.frame_end,camera=s.camera.name if s.camera else None,
            resolution=[s.render.resolution_x,s.render.resolution_y,s.render.resolution_percentage],
            fps=s.render.fps,engine=s.render.engine,
            strips=[dict(name=t.name,start=t.frame_start,first=t.frame_final_start,last=t.frame_final_end,
                scene=t.scene.name if t.type=='SCENE' else None) for t in s.sequence_editor.strips] if s.sequence_editor else []) for s in bpy.data.scenes})
