"""Direct sRGB weather display without second lighting or colour enhancement."""
import bpy


def weather(name,first,frames=1,hold=32,transparent_missing=False):
    material=bpy.data.materials.new(name); material.use_nodes=True
    nodes=material.node_tree.nodes; links=material.node_tree.links; nodes.clear()
    output=nodes.new('ShaderNodeOutputMaterial'); emission=nodes.new('ShaderNodeEmission')
    texture=nodes.new('ShaderNodeTexImage')
    texture.image=bpy.data.images.load(str(first),check_existing=False)
    texture.image.colorspace_settings.name='sRGB'
    texture.interpolation='Linear'; texture.extension='EXTEND'
    if frames>1:
        texture.image.source='SEQUENCE'; user=texture.image_user
        # Blender clamps the display frame to frame_duration before applying
        # frame_offset. Use the display duration, not the source-file count.
        user.frame_duration=frames*hold; user.frame_start=1; user.use_auto_refresh=True
        user.driver_add('frame_offset').driver.expression=(
            f'min({frames},max(1,floor((frame-1)/{hold})+1))-min({frames*hold},max(0,frame))')
    if transparent_missing:
        mix=nodes.new('ShaderNodeMixShader'); transparent=nodes.new('ShaderNodeBsdfTransparent')
        links.new(texture.outputs['Alpha'],mix.inputs[0]); links.new(transparent.outputs[0],mix.inputs[1])
        links.new(texture.outputs['Color'],emission.inputs['Color']); links.new(emission.outputs[0],mix.inputs[2])
        links.new(mix.outputs[0],output.inputs['Surface'])
    else:
        mix=nodes.new('ShaderNodeMixRGB'); mix.blend_type='MIX'; mix.inputs[1].default_value=(.008,.008,.008,1)
        links.new(texture.outputs['Alpha'],mix.inputs[0]); links.new(texture.outputs['Color'],mix.inputs[2])
        links.new(mix.outputs[0],emission.inputs['Color']); links.new(emission.outputs[0],output.inputs['Surface'])
    return material
