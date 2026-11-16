"""Deterministic opaque ray display: native surface + broader grazing blue air.

An artistic optical-depth approximation, not a retrieved/physical atmosphere.
No transparent closure, stochastic alpha or volume integration is used.
"""
import math

from .native_disk_material import A, B, texture_color
from .rim import linear
from .shader_math import Nodes
from .ellipsoid_mesh import create as ellipsoid

CONTROLS = [
    ('blueDensity', '蓝色大气浓度', 0, 2.5, 1),
    ('blueThickness', '蓝色大气厚度', .5, 2, 1),
    ('blueHue', '蓝色大气色相（度）', -180, 180, 0),
    ('blueSaturation', '蓝色大气饱和度', 0, 2, 1),
    ('blueBrightness', '蓝色大气亮度', 0, 3, 1),
    ('warmDensity', '夜间气辉浓度', 0, 2.5, 1),
    ('warmThickness', '夜间气辉厚度', .5, 2, 1),
    ('warmHue', '夜间气辉色相（度）', -180, 180, 0),
    ('warmSaturation', '夜间气辉饱和度', 0, 2, 1),
    ('warmBrightness', '夜间气辉亮度', 0, 3, 1),
]


def optional_value(n, control, paths, key, default):
    path = paths.get('["'+key+'"]')
    return object_value(n, control, path, key) if path else default


def adjust_color(n, color, control, paths, prefix):
    node = n.node('ShaderNodeHueSaturation')
    node.label = prefix+' · 独立颜色调整'
    n.put((*color, 1) if isinstance(color, tuple) else color, node.inputs['Color'])
    n.put(n.m('ADD', .5, n.m('DIVIDE', optional_value(n, control, paths, prefix+'Hue', 0), 360)), node.inputs['Hue'])
    n.put(optional_value(n, control, paths, prefix+'Saturation', 1), node.inputs['Saturation'])
    n.put(optional_value(n, control, paths, prefix+'Brightness', 1), node.inputs['Value'])
    return node.outputs['Color']


def blue_weight(height_km, mu, density=1, thickness=1, inside=False):
    if inside:
        tau = .029*density*(1-mu)**2/math.sqrt((mu/(thickness*1.15))**2+24/6371)
    else:
        tau = .78*density*math.exp(-max(height_km, 0)/(18*thickness))
    return 1-math.exp(-tau)


def object_value(n, control, path, label):
    node = n.node('ShaderNodeValue')
    node.label = label
    driver = node.outputs[0].driver_add('default_value').driver
    variable = driver.variables.new()
    variable.name = 'value'
    variable.targets[0].id = control
    variable.targets[0].data_path = path
    driver.expression = 'value'
    return node.outputs[0]


def create(scene, master, assets, images, sun, control, paths):
    import bpy
    material = bpy.data.materials.new('分层空气感 · 原生纹理与大气解析合成 · '+scene.name)
    material.use_nodes = True
    n = Nodes(material.node_tree)
    m, v = n.m, n.v
    geometry, camera = n.node('ShaderNodeNewGeometry'), n.node('ShaderNodeCameraData')
    incoming = v('NORMALIZE', geometry.outputs['Incoming'])
    # Reconstruct true camera origin even if the camera enters the outer proxy.
    origin_world = v('ADD', geometry.outputs['Position'], v('SCALE', incoming, camera.outputs['View Distance']))
    inv = (1/A, 1/A, 1/B)
    origin = v('MULTIPLY', origin_world, inv)
    ray = v('MULTIPLY', v('SCALE', incoming, -1), inv)
    a = v('DOT_PRODUCT', ray, ray)
    t = m('DIVIDE', m('MULTIPLY', v('DOT_PRODUCT', origin, ray), -1), a)
    closest = v('ADD', origin, v('SCALE', ray, t))
    impact = v('LENGTH', closest)
    h = m('MULTIPLY', m('SUBTRACT', impact, 1), 6371)
    chord = m('SQRT', m('DIVIDE', m('MAXIMUM', 0, m('SUBTRACT', 1, m('MULTIPLY', impact, impact))), a))
    hit = m('SUBTRACT', t, chord)
    inside = m('MULTIPLY', m('LESS_THAN', impact, 1), m('GREATER_THAN', hit, 0))
    forward = m('GREATER_THAN', t, 0)
    hit_scaled = v('ADD', origin, v('SCALE', ray, hit))
    point = v('ADD', v('SCALE', hit_scaled, inside), v('SCALE', closest, m('SUBTRACT', 1, inside)))
    normal = v('NORMALIZE', v('MULTIPLY', point, inv))
    mu = m('MINIMUM', 1, m('MAXIMUM', 0, v('DOT_PRODUCT', normal, incoming)))
    density = object_value(n, control, paths['["blueDensity"]'], '蓝色大气浓度')
    thickness = object_value(n, control, paths['["blueThickness"]'], '蓝色大气厚度')
    scaled_mu = m('DIVIDE', mu, m('MULTIPLY', 1.15, m('MAXIMUM', .5, thickness)))
    taper = m('SUBTRACT', 1, mu)
    inside_tau = m('DIVIDE', m('MULTIPLY', m('MULTIPLY', .029, density), m('MULTIPLY', taper, taper)),
                   m('SQRT', m('ADD', m('MULTIPLY', scaled_mu, scaled_mu), 24/6371)))
    outside_tau = m('MULTIPLY', m('MULTIPLY', .78, density), m('EXPONENT',
        m('DIVIDE', m('MULTIPLY', m('MAXIMUM', 0, h), -1), m('MULTIPLY', 18, thickness))))
    tau = m('ADD', m('MULTIPLY', inside_tau, inside), m('MULTIPLY', outside_tau, m('SUBTRACT', 1, inside)))
    if isinstance(sun,dict):
        # Native node curves follow the editable weather clock without handlers.
        clock=object_value(n,control,paths['["weatherHours"]'],'天气时间 UTC−7')
        clock_start=sun.get('clock_start',6);clock_end=sun.get('clock_end',18)
        progress=m('DIVIDE',m('SUBTRACT',clock,clock_start),clock_end-clock_start)
        components=[]
        for axis in range(3):
            curve=n.node('ShaderNodeFloatCurve');curve.label='UTC太阳方向 '+str(axis)
            curve.mapping.initialize();curve.mapping.use_clip=False
            points=curve.mapping.curves[0].points
            points[0].location=(0,sun['vectors'][0][axis]);points[-1].location=(1,sun['vectors'][-1][axis])
            for index,vector in enumerate(sun['vectors'][1:-1],1):points.new(index/(len(sun['vectors'])-1),vector[axis])
            for point in points:point.handle_type='VECTOR'
            curve.mapping.update();n.put(progress,curve.inputs['Value']);components.append(curve.outputs['Value'])
        sun=v('NORMALIZE',n.combine(components))
    dot = v('DOT_PRODUCT', normal, sun)
    x = m('MINIMUM', 1, m('MAXIMUM', 0, m('DIVIDE', m('ADD', dot, .104528), .209056)))
    day = m('MULTIPLY', m('MULTIPLY', m('MULTIPLY', x, x), x), m('ADD', m('MULTIPLY', x, m('SUBTRACT', m('MULTIPLY', 6, x), 15)), 10))
    blue = m('MULTIPLY', m('MULTIPLY', m('SUBTRACT', 1, m('EXPONENT', m('MULTIPLY', tau, -1))), day),
             object_value(n, control, paths['["blueAtmosphere"]'], '蓝色大气开关'))
    # Default reproduces the original warm profile; its strength/width are independent.
    warm_density = optional_value(n, control, paths, 'warmDensity', 1)
    warm_thickness = optional_value(n, control, paths, 'warmThickness', 1)
    width = m('MULTIPLY', m('SUBTRACT', 18, m('MULTIPLY', inside, 16)), warm_thickness)
    ratio = m('DIVIDE', h, width)
    warm = m('MULTIPLY', m('MULTIPLY', m('MULTIPLY', m('EXPONENT', m('MULTIPLY', m('MULTIPLY', ratio, ratio), -.5)),
             m('SUBTRACT', 1, day)), m('MULTIPLY', .12, warm_density)), object_value(n, control, paths['["nightAirglow"]'], '夜间气辉开关'))
    # At maximum thickness, fade smoothly before the proxy mesh boundary.
    edge = m('MINIMUM', 1, m('MAXIMUM', 0, m('DIVIDE', m('SUBTRACT', h, 224), 32)))
    edge = m('MULTIPLY', m('MULTIPLY', edge, edge), m('SUBTRACT', 3, m('MULTIPLY', 2, edge)))
    visible = m('MULTIPLY', forward, m('SUBTRACT', 1, edge))
    blue, warm = m('MULTIPLY', blue, visible), m('MULTIPLY', warm, visible)
    pale = tuple(linear(c) for c in (.46, .62, .78))
    upper = tuple(linear(c) for c in (.24, .42, .68))
    altitude = m('MINIMUM', 1, m('DIVIDE', m('MAXIMUM', 0, h), m('MULTIPLY', 60, thickness)))
    blue_color = v('ADD', v('SCALE', pale, m('SUBTRACT', 1, altitude)), v('SCALE', upper, altitude))
    warm_color = tuple(linear(c) for c in (.46, .40, .32))
    blue_color = adjust_color(n, blue_color, control, paths, 'blue')
    warm_color = adjust_color(n, warm_color, control, paths, 'warm')
    ground_point = v('MULTIPLY', hit_scaled, (A, A, B))
    ground = v('SCALE', texture_color(n, ground_point, master, assets, images), inside)
    result = v('ADD', v('SCALE', ground, m('SUBTRACT', 1, m('ADD', blue, warm))),
               v('ADD', v('SCALE', blue_color, blue), v('SCALE', warm_color, warm)))
    emission = n.node('ShaderNodeEmission')
    n.put(result, emission.inputs['Color'])
    n.put(emission.outputs[0], n.node('ShaderNodeOutputMaterial').inputs['Surface'])
    obj = ellipsoid('地球与分层大气 · '+scene.name, tuple(r*(1+256/6371) for r in (A, A, B)), 512, 256)
    obj.data.materials.append(material)
    obj.hide_select = True
    obj['earthstudio_layered_atmosphere'] = True
    obj['model'] = 'Artistic optical depth; native sensor texture; opaque analytic camera rays; no volume/transparent noise'
    scene['earthstudio_atmosphere_profile'] = 'layered-optical-display-v3'
    return obj
