"""Native, sparse Blender parameter curves; no runtime Python handlers required.

The hierarchy implements Cesium's WGS84 ENU orbit exactly, at 1 unit/1e6 m.
Monotone Hermite progress is converted to cubic Bezier handles with linear time.
Free-pose tracks retain the existing baked-camera fallback.
"""
import math
import bpy

PARAMETERS = ('targetLon', 'targetLat', 'heading', 'pitch', 'rangeKm', 'roll', 'fov')
LABELS = ('目标经度 °', '目标纬度 °', '绕目标角度 °', '俯看角度 °', '距目标 km', '画面旋转 °', '垂直画角 °')
SMOOTH = [[0, 0], [.2, .07], [.8, .93], [1, 1]]


def slopes(points):
    h = [b[0]-a[0] for a, b in zip(points, points[1:])]
    d = [(b[1]-a[1])/step for a, b, step in zip(points, points[1:], h)]
    return [d[0]] + [0 if d[i-1]*d[i] <= 0 else
        3*(h[i-1]+h[i])/((2*h[i]+h[i-1])/d[i-1]+(h[i]+2*h[i-1])/d[i])
        for i in range(1, len(points)-1)] + [d[-1]]


def curves(owner):
    action = owner.animation_data.action
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    return [c for layer in action.layers for strip in layer.strips
            for bag in strip.channelbags for c in bag.fcurves]


def parameter_points(keys, parameter, track, fps):
    """Return frame/value plus incoming/outgoing slopes, matching timeline.js."""
    result = []
    value = keys[0]['orbit'][parameter]
    for a, b in zip(keys, keys[1:]):
        delta = b['orbit'][parameter]-a['orbit'][parameter]
        if parameter == 'targetLon':
            delta = (delta+180) % 360-180
        start, span = 1+a['time']*fps, (b['time']-a['time'])*fps
        points = a.get('curve') or track.get('curve') or (SMOOTH if track.get('easing') == 'smooth' else [[0, 0], [1, 1]])
        if b.get('transition') == 'cut':
            points = [[0, 0], [1, 1]]
        derivatives = slopes(points)
        for i, (x, y) in enumerate(points):
            frame, val = start+x*span, value+delta*y
            slope = delta*derivatives[i]/span
            if result and abs(result[-1]['frame']-frame) < 1e-6:
                result[-1]['right'] = slope
                result[-1]['cut'] = b.get('transition') == 'cut'
            else:
                result.append(dict(frame=frame, value=val, left=slope, right=slope,
                                   cut=b.get('transition') == 'cut' and i == 0))
        value += delta
    if not result:
        result = [dict(frame=1+keys[0]['time']*fps, value=value, left=0, right=0, cut=False)]
    return result


def driver(owner, path, index, controller, expression, names):
    curve = owner.driver_add(path) if index is None else owner.driver_add(path, index)
    d = curve.driver
    d.type = 'SCRIPTED'
    for name in names:
        variable = d.variables.new()
        variable.name = name
        variable.targets[0].id = controller
        variable.targets[0].data_path = '["'+name+'"]'
    d.expression = expression


def create(scene, track, reference):
    keys = track.get('keyframeTrack', {}).get('keys', [])
    if not keys or not all(key.get('orbit') for key in keys):
        reference['earthstudio_edit_mode'] = 'Baked free-pose camera; native orbit conversion unavailable'
        return None
    name = track.get('name', 'Take')
    collection = bpy.data.collections.new(name+' · 可编辑运镜')
    scene.collection.children.link(collection)

    def empty(label, parent=None):
        obj = bpy.data.objects.new(name+' · '+label, None)
        collection.objects.link(obj)
        obj.empty_display_size = .15
        obj.parent = parent
        return obj

    control = empty('参数控制器')
    control['earthstudio_editable_track'] = track['keyframeTrack']['id']
    control['earthstudio_source_key_count'] = len(keys)
    control['earthstudio_duration_seconds'] = track['samples'][-1]['seconds']
    for parameter, label in zip(PARAMETERS, LABELS):
        control[parameter] = float(keys[0]['orbit'][parameter])
        control.id_properties_ui(parameter).update(description=label)
        points = parameter_points(keys, parameter, track['keyframeTrack'], track['fps'])
        path = '["'+parameter+'"]'
        for point in points:
            # JSON often contains whole numbers. Preserve a FLOAT ID property:
            # integer properties quantize animation between keys in Blender.
            control[parameter] = float(point['value'])
            control.keyframe_insert(path, frame=point['frame'], group=label)
        curve = next(c for c in curves(control) if c.data_path == path)
        curve.extrapolation = 'CONSTANT'
        for i, (key, point) in enumerate(zip(curve.keyframe_points, points)):
            key.interpolation = 'CONSTANT' if point['cut'] else 'BEZIER'
            key.handle_left_type = key.handle_right_type = 'FREE'
            before = (point['frame']-points[i-1]['frame'])/3 if i else 1/3
            after = (points[i+1]['frame']-point['frame'])/3 if i+1 < len(points) else 1/3
            key.handle_left = (point['frame']-before, point['value']-before*point['left'])
            key.handle_right = (point['frame']+after, point['value']+after*point['right'])
    target = empty('WGS84 目标')
    # Geodetic position. Driver expressions deliberately use Blender's simple math subset.
    r = '(6378137/sqrt(1-0.0066943799901413165*sin(targetLat*pi/180)**2))'
    for i, expression in enumerate((r+'*cos(targetLat*pi/180)*cos(targetLon*pi/180)/1000000',
                                   r+'*cos(targetLat*pi/180)*sin(targetLon*pi/180)/1000000',
                                   r+'*(1-0.0066943799901413165)*sin(targetLat*pi/180)/1000000')):
        driver(target, 'location', i, control, expression, ['targetLat', 'targetLon'])
    driver(target, 'rotation_euler', 2, control, '(targetLon+90)*pi/180', ['targetLon'])
    tilt = empty('当地地平面', target)
    driver(tilt, 'rotation_euler', 0, control, '(90-targetLat)*pi/180', ['targetLat'])
    heading = empty('绕目标', tilt)
    driver(heading, 'rotation_euler', 2, control, '-heading*pi/180', ['heading'])
    pitch = empty('俯看', heading)
    driver(pitch, 'rotation_euler', 0, control, '(90+pitch)*pi/180', ['pitch'])
    data = bpy.data.cameras.new(name+' · 可编辑相机')
    camera = bpy.data.objects.new(data.name, data)
    collection.objects.link(camera)
    camera.parent = pitch
    data.sensor_fit = 'HORIZONTAL'
    data.sensor_width = 36
    data.clip_start, data.clip_end = .00001, 1000
    driver(camera, 'location', 2, control, 'rangeKm/1000', ['rangeKm'])
    driver(camera, 'rotation_euler', 2, control, 'roll*pi/180', ['roll'])
    aspect = track['samples'][0]['aspect']
    driver(data, 'lens', None, control, f'36/(2*tan(fov*pi/360)*{aspect!r})', ['fov'])
    camera['earthstudio_editable_camera'] = track['keyframeTrack']['id']
    camera['earthstudio_controller'] = control.name
    camera['earthstudio_reference_camera'] = reference.name
    camera['earthstudio_duration_seconds'] = track['samples'][-1]['seconds']
    reference['earthstudio_edit_mode'] = 'Baked comparison camera; editable parameter rig also present'
    return camera
