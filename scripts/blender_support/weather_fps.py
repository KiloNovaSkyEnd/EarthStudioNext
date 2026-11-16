"""Independent observation clock. Only the weather F-curve is replaced."""
import json
import math


def seconds_for(start, end, interval, fps):
    if not all(math.isfinite(x) for x in (start, end, interval, fps)) or end < start or interval <= 0 or not .000001 <= fps <= 120:
        raise ValueError('Invalid observation rate or interval')
    return (end-start)*3600/interval/fps


def apply(control, path, start, end, interval, fps, render_fps=30, first_frame=1):
    from scripts.blender_support.editable_camera import curves
    seconds = seconds_for(start, end, interval, fps)
    if render_fps <= 0:
        raise ValueError('Invalid render fps')
    if control.animation_data and control.animation_data.action:
        for curve in curves(control):
            if curve.data_path == path:
                curve.keyframe_points.clear()
    owner, attribute = path.rsplit('.', 1)
    values = [(first_frame, start)]
    if seconds > 0:
        values.append((first_frame+seconds*render_fps, end))
    for frame, value in values:
        setattr(control.path_resolve(owner), attribute, float(value))
        control.keyframe_insert(path, frame=frame)
    curve = next(c for c in curves(control) if c.data_path == path)
    curve.extrapolation = 'CONSTANT'
    for key in curve.keyframe_points:
        key.interpolation = 'LINEAR'
    return seconds


def configure(scene, start, end, interval, fps):
    seconds_for(start, end, interval, fps)
    for key, value in [('start', start), ('end', end), ('interval', interval), ('fps', fps)]:
        scene['earthstudio_weather_'+key] = float(value)
    scene.id_properties_ui('earthstudio_weather_fps').update(min=.000001, max=120, description='观测时次/秒，与成片fps及相机时长独立。点应用后更新天气曲线。')


def apply_scene(scene):
    control = __import__('bpy').data.objects[scene.camera['earthstudio_controller']]
    path = json.loads(control['earthstudio_parameter_paths'])['["weatherHours"]']
    return apply(control, path, *(scene['earthstudio_weather_'+k] for k in ['start', 'end', 'interval', 'fps']),
                 render_fps=scene.render.fps/scene.render.fps_base, first_frame=scene.frame_start)
