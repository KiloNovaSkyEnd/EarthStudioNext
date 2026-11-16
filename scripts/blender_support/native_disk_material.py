"""Project ECEF directly into the ORIGINAL 16 sensor image pages in shader.

No geographic proxy, resampled global texture or camera-local texture cache.
All native pixels remain available when the user changes camera in Blender.
"""
import math
from pathlib import Path

A, B = 6.378137, 6.356752314245
H, HEIGHT, LON = 42.164, 35.785863, math.radians(140.7)


def project_ecef(position):
    """CPU oracle for the node math, metres in and geostationary metres out."""
    x, y, z = [value/1e6 for value in position]
    x, y = math.cos(LON)*x+math.sin(LON)*y, -math.sin(LON)*x+math.cos(LON)*y
    vx = H-x
    visible = x*vx-y*y-z*z*(A/B)**2 > 0
    return HEIGHT*1e6*math.atan2(y, vx), HEIGHT*1e6*math.atan2(z, math.hypot(vx, y)), visible


def texture_color(n, exact, master, assets, image_cache=None):
    """Native linear RGB at an ECEF point, reusable by analytic camera rays."""
    import bpy
    m, v = n.m, n.v
    px, py, z = n.xyz(exact)
    if master.get('projection') == 'geographic_preview':
        # Display-only equirectangular video; render surface remains geostationary.
        texture = n.node('ShaderNodeTexImage')
        texture.image = image_cache['video']
        texture.interpolation, texture.extension = 'Linear', 'EXTEND'
        longitude = m('ARCTAN2', py, px)
        latitude = m('ARCTAN2', m('MULTIPLY', z, (A / B) ** 2), m('SQRT', m('ADD', m('MULTIPLY', px, px), m('MULTIPLY', py, py))))
        uv = n.combine((m('ADD', .5, m('DIVIDE', longitude, 2 * math.pi)), m('ADD', .5, m('DIVIDE', latitude, math.pi)), 0))
        n.put(uv, texture.inputs['Vector'])
        return texture.outputs['Color']
    x = m('ADD', m('MULTIPLY', px, math.cos(LON)), m('MULTIPLY', py, math.sin(LON)))
    y = m('ADD', m('MULTIPLY', px, -math.sin(LON)), m('MULTIPLY', py, math.cos(LON)))
    vx = m('SUBTRACT', H, x)
    gx = m('MULTIPLY', m('ARCTAN2', y, vx), HEIGHT*1e6)
    gy = m('MULTIPLY', m('ARCTAN2', z, m('SQRT', m('ADD', m('MULTIPLY', vx, vx), m('MULTIPLY', y, y)))), HEIGHT*1e6)
    visible = m('GREATER_THAN', m('SUBTRACT', m('SUBTRACT', m('MULTIPLY', x, vx), m('MULTIPLY', y, y)), m('MULTIPLY', m('MULTIPLY', z, z), (A/B)**2)), 0)
    if master.get('production_layers'):
        from .production_layers import color
        return color(n, gx, gy, visible, master, assets)
    total, alpha = (0, 0, 0), 0
    for tile in master['tiles']:
        print('NATIVE_IMAGE', tile['path'], flush=True)
        image = image_cache.get(tile['path']) if image_cache else None
        if image is None:
            image = bpy.data.images.load(str(Path(assets)/tile['path']), check_existing=True)
        if list(image.size)[::-1] != tile['shape']:
            raise ValueError('Blender image dimensions differ from native receipt')
        image.colorspace_settings.name = 'sRGB'
        image.alpha_mode = 'STRAIGHT'
        texture = n.node('ShaderNodeTexImage')
        texture.image = image
        texture.interpolation, texture.extension = 'Linear', 'CLIP'
        texture.label = tile['path']+' · native pixels'
        left, bottom, right, top = tile['extent']
        uv = n.combine((m('DIVIDE', m('SUBTRACT', gx, left), right-left), m('DIVIDE', m('SUBTRACT', gy, bottom), top-bottom), 0))
        n.put(uv, texture.inputs['Vector'])
        core = tile['coreWindow']
        dx, dy = tile['transform'][0], -tile['transform'][4]
        west = left+core['sourceX']*dx
        north = top-core['sourceY']*dy
        east, south = west+core['width']*dx, north-core['height']*dy
        mask = visible
        for value, lo, hi in ((gx, west, east), (gy, south, north)):
            mask = m('MULTIPLY', mask, m('SUBTRACT', 1, m('LESS_THAN', value, lo)))
            mask = m('MULTIPLY', mask, m('LESS_THAN', value, hi))
        weight = m('MULTIPLY', mask, texture.outputs['Alpha'])
        total = v('ADD', total, v('SCALE', texture.outputs['Color'], weight))
        alpha = m('ADD', alpha, weight)
    # Opaque neutral missing-data indicator prevents seeing the far side through gaps.
    color = v('ADD', total, v('SCALE', (.008, .008, .008), m('SUBTRACT', 1, alpha)))
    return color


def create(scene, master, assets):
    import bpy
    from .shader_math import Nodes
    material = bpy.data.materials.new('H9 stock GeoColor · original 22000 sensor grid')
    material.use_nodes = True
    n = Nodes(material.node_tree)
    geometry = n.node('ShaderNodeNewGeometry')
    # Correct chord-interpolated mesh position onto the actual ellipsoid.
    pos = geometry.outputs['Position']
    length = n.v('LENGTH', n.v('MULTIPLY', pos, (1/A, 1/A, 1/B)))
    exact = n.v('SCALE', pos, n.m('DIVIDE', 1, length))
    color = texture_color(n, exact, master, assets)
    emission = n.node('ShaderNodeEmission')
    n.put(color, emission.inputs['Color'])
    output = n.node('ShaderNodeOutputMaterial')
    n.put(emission.outputs[0], output.inputs['Surface'])
    print('BUILD_WGS84_MESH', flush=True)
    from .ellipsoid_mesh import create as ellipsoid
    globe = ellipsoid('WGS84 Earth · native H9 2026-10-20 22:40 UTC', (A, A, B))
    globe.data.materials.append(material)
    globe['native_master_shape'] = master['shape']
    globe['missing_data'] = 'Neutral grey = no H9 observation; no static ground infill'
    globe['texture_mapping'] = 'Analytic geostationary sweep-y; 16 native RGBA pages, no downsample'
    return globe
