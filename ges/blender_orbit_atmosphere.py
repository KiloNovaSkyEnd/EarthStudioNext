"""Independent Blender volume / ray-integral candidate; observations unchanged.

All distances km. Standard exponential gas/aerosol profiles and a declared
night emission model, not an atmospheric retrieval. Cycles evaluates actual
camera/light paths; no camera-facing cards or pre-rendered atmosphere images.
"""
RADIUS = 6371.


class Graph:
    def __init__(self, material):
        self.nodes = material.node_tree.nodes
        self.links = material.node_tree.links
        self.nodes.clear()

    def node(self, kind, **properties):
        node = self.nodes.new(kind)
        for key, value in properties.items():
            setattr(node, key, value)
        return node

    def connect(self, value, socket):
        if isinstance(value, (int, float, tuple, list)):
            socket.default_value = value
        else:
            self.links.new(value, socket)

    def op(self, operation, *values):
        node = self.node('ShaderNodeMath', operation=operation)
        for value, socket in zip(values, node.inputs):
            self.connect(value, socket)
        return node.outputs[0]

    def vec(self, operation, *values):
        node = self.node('ShaderNodeVectorMath', operation=operation)
        for value, socket in zip(values, node.inputs):
            self.connect(value, socket)
        return node.outputs['Value' if operation in ('LENGTH', 'DOT_PRODUCT') else 'Vector']

    def smooth(self, value, low, high, start=0., end=1.):
        node = self.node('ShaderNodeMapRange', clamp=True, interpolation_type='SMOOTHERSTEP')
        self.connect(value, node.inputs['Value'])
        for name, val in [('From Min', low), ('From Max', high), ('To Min', start), ('To Max', end)]:
            node.inputs[name].default_value = val
        return node.outputs['Result']

    def scale(self, vector, factor):
        node = self.node('ShaderNodeVectorMath', operation='SCALE')
        self.connect(vector, node.inputs[0])
        self.connect(factor, node.inputs['Scale'])
        return node.outputs['Vector']

    def control(self, scene, key):
        node = self.node('ShaderNodeValue', label=key)
        driver = node.outputs[0].driver_add('default_value').driver
        driver.expression = 'control'
        variable = driver.variables.new()
        variable.name = 'control'
        variable.targets[0].id_type = 'SCENE'
        variable.targets[0].id = scene
        variable.targets[0].data_path = '["' + key + '"]'
        return node.outputs[0]


def material(name):
    import bpy
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    return result


def sphere(name, radius, segments=192, rings=96):
    import bpy
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, radius=radius)
    obj = bpy.context.object
    obj.name = name
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def install(scene, sun):
    import bpy
    for key, value in [('ES_atmosphere_gain', 1.), ('ES_airglow_gain', 1.)]:
        scene[key] = value
        scene.id_properties_ui(key).update(min=0., max=2., description='Display model control; not a measured quantity')
    scene['ES_atmosphere_model'] = 'Blender Cycles exponential Rayleigh/Mie candidate; not previous GLSL model'
    scene['ES_airglow_model'] = '48-cell camera-ray integral of Gaussian 90km / 7km emission; night gated, not measured'
    body = sphere('Atmosphere_volume', RADIUS+150.)
    mat = material('Atmosphere: actual Cycles volume paths')
    mat.cycles.volume_sampling = 'DISTANCE'
    body.data.materials.append(mat)
    graph = Graph(mat)
    output = graph.node('ShaderNodeOutputMaterial')
    geo = graph.node('ShaderNodeNewGeometry')
    radius = graph.vec('LENGTH', geo.outputs['Position'])
    height = graph.op('MAXIMUM', graph.op('SUBTRACT', radius, RADIUS), 0.)
    above = graph.op('GREATER_THAN', radius, RADIUS-.01)
    normal = graph.vec('NORMALIZE', geo.outputs['Position'])
    solar = graph.vec('DOT_PRODUCT', normal, tuple(sun))
    day = graph.smooth(solar, -.104528, .104528)
    gain = graph.op('MULTIPLY', graph.control(scene, 'ES_atmosphere_gain'), above)
    # On the night side IR is a display signal, not visible radiance. Use
    # neutral extinction to avoid spuriously yellowing its false-colour clouds.
    # Avoid a Blender 5.2.1 Cycles volume-optimizer crash in MixRGB.
    tint = graph.node('ShaderNodeCombineXYZ')
    graph.connect(graph.op('ADD', .4096, graph.op('MULTIPLY', day, -.2343)), tint.inputs[0])
    tint.inputs[1].default_value = .4096
    graph.connect(graph.op('ADD', .4096, graph.op('MULTIPLY', day, .5904)), tint.inputs[2])
    rayleigh = graph.node('ShaderNodeVolumeScatter', label='Rayleigh approximate isotropic phase')
    graph.connect(tint.outputs[0], rayleigh.inputs['Color'])
    rayleigh.inputs['Anisotropy'].default_value = 0.
    ray_density = graph.op('MULTIPLY', graph.op('EXPONENT', graph.op('DIVIDE', height, -8.)), .0331)
    graph.connect(graph.op('MULTIPLY', ray_density, gain), rayleigh.inputs['Density'])
    mie = graph.node('ShaderNodeVolumeScatter', label='Mie HG phase')
    mie.inputs['Color'].default_value = (.9, .9, .9, 1.)
    mie.inputs['Anisotropy'].default_value = .76
    mie_density = graph.op('MULTIPLY', graph.op('EXPONENT', graph.op('DIVIDE', height, -1.2)), .003996)
    graph.connect(graph.op('MULTIPLY', mie_density, gain), mie.inputs['Density'])
    combined = graph.node('ShaderNodeAddShader')
    graph.links.new(rayleigh.outputs[0], combined.inputs[0])
    graph.links.new(mie.outputs[0], combined.inputs[1])
    graph.links.new(combined.outputs[0], output.inputs['Volume'])

    # A deterministic emission integral avoids emission-only overlapping
    # volumes changing Cycles' sampling strategy/noise in the atmosphere.
    glow = sphere('Airglow_ray_integral_shell', RADIUS+130.)
    glow.visible_shadow = False
    glow.visible_diffuse = False
    glow.visible_glossy = False
    glow.visible_volume_scatter = False
    glowmat = material('Airglow: actual camera-ray altitude quadrature')
    if hasattr(glowmat.cycles, 'emission_sampling'):
        glowmat.cycles.emission_sampling = 'NONE'
    glow.data.materials.append(glowmat)
    graph = Graph(glowmat)
    output = graph.node('ShaderNodeOutputMaterial')
    geo = graph.node('ShaderNodeNewGeometry')
    incoming = graph.vec('NORMALIZE', geo.outputs['Incoming'])
    along = graph.vec('DOT_PRODUCT', geo.outputs['Position'], incoming)
    closest = graph.vec('SUBTRACT', geo.outputs['Position'], graph.scale(incoming, along))
    impact = graph.vec('LENGTH', closest)
    half = graph.op('SQRT', graph.op('MAXIMUM', graph.op('SUBTRACT', (RADIUS+130.)**2,
                                                                     graph.op('MULTIPLY',impact,impact)),0.))
    total = 0.
    for i in range(48):
        t = graph.op('MULTIPLY',half,-1.+(i+.5)*2/48)
        point = graph.vec('ADD',closest,graph.scale(incoming,t))
        radius = graph.vec('LENGTH',point)
        h = graph.op('SUBTRACT',radius,RADIUS)
        sigma = graph.op('DIVIDE',graph.op('SUBTRACT',h,90.),7.)
        profile = graph.op('EXPONENT',graph.op('MULTIPLY',graph.op('MULTIPLY',sigma,sigma),-.5))
        normal = graph.vec('NORMALIZE',point)
        solar = graph.vec('DOT_PRODUCT',normal,tuple(sun))
        night = graph.smooth(solar,-.309017,-.104528,1.,0.)
        total = graph.op('ADD',total,graph.op('MULTIPLY',profile,night))
    strength = graph.op('MULTIPLY',graph.op('MULTIPLY',total,half),2/48*.000003)
    strength = graph.op('MULTIPLY',strength,graph.control(scene,'ES_airglow_gain'))
    strength = graph.op('MULTIPLY',strength,graph.op('GREATER_THAN',impact,RADIUS))
    strength = graph.op('MULTIPLY',strength,graph.op('SUBTRACT',1.,geo.outputs['Backfacing']))
    light_path = graph.node('ShaderNodeLightPath')
    strength = graph.op('MULTIPLY',strength,light_path.outputs['Is Camera Ray'])
    emission = graph.node('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (.8, .38, .10, 1.)
    graph.connect(strength, emission.inputs['Strength'])
    transparent = graph.node('ShaderNodeBsdfTransparent')
    add = graph.node('ShaderNodeAddShader')
    graph.links.new(transparent.outputs[0],add.inputs[0])
    graph.links.new(emission.outputs[0],add.inputs[1])
    graph.links.new(add.outputs[0],output.inputs['Surface'])
    return body, glow
