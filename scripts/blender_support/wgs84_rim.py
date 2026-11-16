"""Approved Gaussian rim in WGS84 scaled ray space, independent scene switches."""
import bpy
from .shader_math import Nodes
from .native_disk_material import A, B
from .rim import linear


def create(scene, sun, settings):
    scene['blueAtmosphere'] = bool(settings.get('blueAtmosphere', True))
    scene['nightAirglow'] = bool(settings.get('nightAirglow', True))
    scene.id_properties_ui('blueAtmosphere').update(description='蓝色大气 · 独立开关')
    scene.id_properties_ui('nightAirglow').update(description='夜间暖气辉 · 独立开关')
    material = bpy.data.materials.new('WGS84 world-space soft rim · independent blue and warm')
    material.use_nodes = True
    n = Nodes(material.node_tree)
    m, v = n.m, n.v
    geometry = n.node('ShaderNodeNewGeometry')
    inv = (1/A, 1/A, 1/B)
    origin = v('MULTIPLY', geometry.outputs['Position'], inv)
    ray = v('MULTIPLY', v('SCALE', geometry.outputs['Incoming'], -1), inv)
    a = v('DOT_PRODUCT', ray, ray)
    t = m('DIVIDE', m('MULTIPLY', v('DOT_PRODUCT', origin, ray), -1), a)
    closest = v('ADD', origin, v('SCALE', ray, t))
    impact = v('LENGTH', closest)
    h = m('MULTIPLY', m('SUBTRACT', impact, 1), 6371)
    inside = m('LESS_THAN', impact, 1)
    width = m('SUBTRACT', 18, m('MULTIPLY', inside, 16))
    ratio = m('DIVIDE', h, width)
    profile = m('EXPONENT', m('MULTIPLY', m('MULTIPLY', ratio, ratio), -.5))
    hit = m('SUBTRACT', t, m('SQRT', m('DIVIDE', m('MAXIMUM', 0, m('SUBTRACT', 1, m('MULTIPLY', impact, impact))), a)))
    point = v('ADD', origin, v('SCALE', ray, m('MULTIPLY', hit, inside)))
    # Outside rays use closest; inside rays use first intersection.
    point = v('ADD', v('SCALE', point, inside), v('SCALE', closest, m('SUBTRACT', 1, inside)))
    normal = v('NORMALIZE', v('MULTIPLY', point, inv))
    dot = v('DOT_PRODUCT', normal, sun)
    x = m('MINIMUM', 1, m('MAXIMUM', 0, m('DIVIDE', m('ADD', dot, .104528), .209056)))
    day = m('MULTIPLY', m('MULTIPLY', m('MULTIPLY', x, x), x), m('ADD', m('MULTIPLY', x, m('SUBTRACT', m('MULTIPLY', 6, x), 15)), 10))
    blue = m('MULTIPLY', m('MULTIPLY', m('MULTIPLY', profile, day), .16), n.prop(scene, 'blueAtmosphere'))
    warm = m('MULTIPLY', m('MULTIPLY', m('MULTIPLY', profile, m('SUBTRACT', 1, day)), .12), n.prop(scene, 'nightAirglow'))
    alpha = m('MULTIPLY', m('ADD', blue, warm), m('SUBTRACT', 1, geometry.outputs['Backfacing']))
    blue_color = tuple(linear(c) for c in (.34, .46, .59))
    warm_color = tuple(linear(c) for c in (.46, .40, .32))
    color = v('SCALE', v('ADD', v('SCALE', blue_color, blue), v('SCALE', warm_color, warm)), m('DIVIDE', 1, m('MAXIMUM', m('ADD', blue, warm), 1e-10)))
    emission = n.node('ShaderNodeEmission')
    n.put(color, emission.inputs['Color'])
    transparent = n.node('ShaderNodeBsdfTransparent')
    mix = n.node('ShaderNodeMixShader')
    n.put(alpha, mix.inputs[0])
    n.put(transparent.outputs[0], mix.inputs[1])
    n.put(emission.outputs[0], mix.inputs[2])
    n.put(mix.outputs[0], n.node('ShaderNodeOutputMaterial').inputs['Surface'])
    from .ellipsoid_mesh import create as ellipsoid
    shell = ellipsoid('Soft atmosphere · scene has two independent switches', tuple(r*(1+108/6371) for r in (A, A, B)), 512, 256)
    shell.data.materials.append(material)
    shell['model'] = 'Display Gaussian, 18km outside/2km inside; not physical scattering or observed airglow'
    return shell
