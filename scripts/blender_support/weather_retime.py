"""Use the same monotone Bezier progress as the camera editor, on a separate weather curve."""
from scripts.blender_support.editable_camera import parameter_points,curves

def apply(control,path,start,end,duration,points=None,fps=30):
    fake=[dict(time=0,orbit={'weather':start}),dict(time=duration,orbit={'weather':end})]
    values=parameter_points(fake,'weather',dict(curve=points or [[0,0],[1,1]]),fps)
    owner,attribute=path.rsplit('.',1)
    for point in values:
        setattr(control.path_resolve(owner),attribute,float(point['value']));control.keyframe_insert(path,frame=point['frame'])
    curve=next(c for c in curves(control) if c.data_path==path);curve.extrapolation='CONSTANT'
    for i,(key,point) in enumerate(zip(curve.keyframe_points,values)):
        key.interpolation='BEZIER';key.handle_left_type=key.handle_right_type='FREE'
        left=(point['frame']-values[i-1]['frame'])/3 if i else 1/3
        right=(values[i+1]['frame']-point['frame'])/3 if i+1<len(values) else 1/3
        key.handle_left=(point['frame']-left,point['value']-left*point['left'])
        key.handle_right=(point['frame']+right,point['value']+right*point['right'])
    return curve
