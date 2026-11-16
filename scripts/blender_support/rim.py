"""World-space tangent-height Gaussian, matching the accepted GLSL profile.

An emission/transparent shell evaluates the ray's distance to Earth's centre.
This is a display model, never a physical atmosphere or observed airglow claim.
"""
import bpy


def linear(c):
    return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4


def create(scene,frames,hold):
    old_interpolation=bpy.context.preferences.edit.keyframe_new_interpolation_type
    bpy.context.preferences.edit.keyframe_new_interpolation_type='CONSTANT'
    material=bpy.data.materials.new('Approved soft rim · world-space Gaussian')
    material.use_nodes=True; nodes=material.node_tree.nodes; links=material.node_tree.links; nodes.clear()
    def math_node(op,a,b=None):
        node=nodes.new('ShaderNodeMath'); node.operation=op
        for i,value in enumerate((a,b)):
            if value is None: continue
            if hasattr(value,'node'): links.new(value,node.inputs[i])
            else: node.inputs[i].default_value=value
        return node.outputs[0]
    def vec(op,a,b=None):
        node=nodes.new('ShaderNodeVectorMath'); node.operation=op
        links.new(a,node.inputs[0])
        if b is not None: links.new(b,node.inputs[1])
        return node.outputs['Value'] if op in ('LENGTH','DOT_PRODUCT','DISTANCE') else node.outputs['Vector']
    geometry=nodes.new('ShaderNodeNewGeometry')
    position,incoming=geometry.outputs['Position'],geometry.outputs['Incoming']
    h=math_node('SUBTRACT',vec('LENGTH',vec('CROSS_PRODUCT',position,incoming)),6371)
    inside=math_node('LESS_THAN',h,0)
    width=math_node('SUBTRACT',18,math_node('MULTIPLY',inside,16))
    ratio=math_node('DIVIDE',h,width)
    profile=math_node('EXPONENT',math_node('MULTIPLY',math_node('MULTIPLY',ratio,ratio),-.5))
    # Surface hit point for inside rays, closest point for rays outside Earth.
    closest_distance=vec('DOT_PRODUCT',position,incoming)
    impact=vec('LENGTH',vec('CROSS_PRODUCT',position,incoming))
    chord=math_node('SQRT',math_node('MAXIMUM',0,math_node('SUBTRACT',6371**2,math_node('MULTIPLY',impact,impact))))
    travel=math_node('SUBTRACT',closest_distance,chord)
    scaled=nodes.new('ShaderNodeVectorMath'); scaled.operation='SCALE'
    links.new(incoming,scaled.inputs[0]); links.new(travel,scaled.inputs['Scale'])
    point=vec('NORMALIZE',vec('SUBTRACT',position,scaled.outputs[0]))
    sun=nodes.new('ShaderNodeCombineXYZ'); sun.label='UTC sun · independent of camera'
    for i,key in enumerate(('sun_x','sun_y','sun_z')):
        scene[key]=frames[0]['sun'][i]
        driver=sun.inputs[i].driver_add('default_value').driver
        variable=driver.variables.new(); variable.name='value'; variable.type='SINGLE_PROP'
        variable.targets[0].id_type='SCENE'; variable.targets[0].id=scene; variable.targets[0].data_path=f'["{key}"]'
        driver.expression='value'
        for index,frame in enumerate(frames):
            scene[key]=frame['sun'][i]; scene.keyframe_insert(data_path=f'["{key}"]',frame=index*hold+1)
    bpy.context.preferences.edit.keyframe_new_interpolation_type=old_interpolation
    # Python keyframe_insert does not consistently use UI interpolation prefs.
    # Blender 5 layered actions require channelbags instead of action.fcurves.
    for layer in scene.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    if curve.data_path in ('["sun_x"]','["sun_y"]','["sun_z"]'):
                        for keyframe in curve.keyframe_points: keyframe.interpolation='CONSTANT'
    # Quintic smootherstep, exactly the GLSL c2 transition.
    t=math_node('DIVIDE',math_node('ADD',vec('DOT_PRODUCT',point,sun.outputs[0]),.104528),.209056)
    t=math_node('MINIMUM',1,math_node('MAXIMUM',0,t))
    day=math_node('MULTIPLY',math_node('MULTIPLY',math_node('MULTIPLY',t,t),t),
        math_node('ADD',math_node('MULTIPLY',t,math_node('SUBTRACT',math_node('MULTIPLY',6,t),15)),10))
    blue=math_node('MULTIPLY',math_node('MULTIPLY',profile,day),.16)
    warm=math_node('MULTIPLY',math_node('MULTIPLY',profile,math_node('SUBTRACT',1,day)),.12)
    alpha=math_node('MULTIPLY',math_node('ADD',blue,warm),math_node('SUBTRACT',1,geometry.outputs['Backfacing']))
    color=nodes.new('ShaderNodeMixRGB')
    color.inputs[1].default_value=tuple(linear(c) for c in (.46,.40,.32))+(1,)
    color.inputs[2].default_value=tuple(linear(c) for c in (.34,.46,.59))+(1,)
    links.new(math_node('DIVIDE',blue,math_node('MAXIMUM',1e-10,math_node('ADD',blue,warm))),color.inputs[0])
    emission=nodes.new('ShaderNodeEmission'); links.new(color.outputs[0],emission.inputs['Color'])
    transparent=nodes.new('ShaderNodeBsdfTransparent'); mix=nodes.new('ShaderNodeMixShader')
    links.new(alpha,mix.inputs[0]); links.new(transparent.outputs[0],mix.inputs[1]); links.new(emission.outputs[0],mix.inputs[2])
    output=nodes.new('ShaderNodeOutputMaterial'); links.new(mix.outputs[0],output.inputs['Surface'])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=256,ring_count=128,radius=6479)
    obj=bpy.context.object; obj.name='Soft atmosphere · toggle render for comparison'; obj.data.materials.append(material)
    for polygon in obj.data.polygons: polygon.use_smooth=True
    return obj
