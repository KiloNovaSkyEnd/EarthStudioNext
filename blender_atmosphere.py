"""Optional analytic limb shaders. No observations or textures are modified."""
import math


def install_atmosphere(scene,config,make_sphere):
    import bpy
    controls=[('GES_day_atmosphere',config['day_enabled'],'Day blue limb: synthetic visualization'),
              ('GES_night_airglow',config['airglow_enabled'],'Night amber airglow: synthetic visualization'),
              ('GES_day_atmosphere_gain',1.,'Day limb display gain'),('GES_night_airglow_gain',1.,'Night airglow display gain')]
    for key,value,desc in controls:
        scene[key]=value
        if isinstance(value,bool):scene.id_properties_ui(key).update(description=desc)
        else:scene.id_properties_ui(key).update(min=0.,max=2.,description=desc)
    scene['GES_atmosphere_is_observation']=False
    scene['GES_atmosphere_model_utc']=config['reference_utc']
    scene['GES_atmosphere_help']='Scene Properties > Custom Properties: independent day blue and night amber toggles; both off = original satellite appearance. Not measured atmosphere.'
    for kind,height,width,color,strength,enable,gain in [
        ('Day_Blue',3.,config['day_width_km'],config['day_linear_rgb'],config['day_strength'],'GES_day_atmosphere','GES_day_atmosphere_gain'),
        ('Night_Amber',config['airglow_height_km'],config['airglow_width_km'],config['airglow_linear_rgb'],config['airglow_strength'],'GES_night_airglow','GES_night_airglow_gain')]:
        obj=make_sphere('Synthetic_Atmosphere_'+kind,6371+config['shell_height_km'],360,180)
        obj['GES_is_measured']=False;obj['GES_display_effect']=kind
        mat=bpy.data.materials.new('OPTIONAL synthetic '+kind+' limb');mat.use_nodes=True;mat.use_backface_culling=True
        if hasattr(mat,'surface_render_method'):mat.surface_render_method='BLENDED'
        elif hasattr(mat,'blend_method'):mat.blend_method='BLEND'
        nodes=mat.node_tree.nodes;nodes.clear();links=mat.node_tree.links
        geo=nodes.new('ShaderNodeNewGeometry')
        def math_node(op,a,b=None):
            n=nodes.new('ShaderNodeMath');n.operation=op
            for i,value in enumerate([a,b]):
                if value is None:continue
                if isinstance(value,(int,float)):n.inputs[i].default_value=value
                else:links.new(value,n.inputs[i])
            return n.outputs[0]
        normal=nodes.new('ShaderNodeVectorMath');normal.operation='NORMALIZE';links.new(geo.outputs['Position'],normal.inputs[0])
        sunlight=nodes.new('ShaderNodeVectorMath');sunlight.operation='DOT_PRODUCT'
        links.new(normal.outputs['Vector'],sunlight.inputs[0]);sunlight.inputs[1].default_value=config['sun_direction_ecef']
        solar=nodes.new('ShaderNodeMapRange');solar.clamp=True;solar.interpolation_type='SMOOTHERSTEP'
        links.new(sunlight.outputs['Value'],solar.inputs['Value']);solar.inputs['From Min'].default_value=-.12;solar.inputs['From Max'].default_value=.12
        solar.inputs['To Min'].default_value=0;solar.inputs['To Max'].default_value=1
        # Impact parameter of the actual camera ray in km. The Gaussian is a
        # declared display profile around a thin limb, not volume scattering.
        cross=nodes.new('ShaderNodeVectorMath');cross.operation='CROSS_PRODUCT'
        links.new(geo.outputs['Position'],cross.inputs[0]);links.new(geo.outputs['Incoming'],cross.inputs[1])
        length=nodes.new('ShaderNodeVectorMath');length.operation='LENGTH';links.new(cross.outputs['Vector'],length.inputs[0])
        offset=math_node('DIVIDE',math_node('SUBTRACT',length.outputs['Value'],6371+height),width)
        profile=math_node('EXPONENT',math_node('MULTIPLY',math_node('MULTIPLY',offset,offset),-1.))
        illumination=solar.outputs['Result'] if kind=='Day_Blue' else math_node('SUBTRACT',1.,solar.outputs['Result'])
        alpha=math_node('MULTIPLY',math_node('MULTIPLY',profile,illumination),strength)
        toggle=nodes.new('ShaderNodeValue');toggle.name='User toggle and gain'
        driver=toggle.outputs[0].driver_add('default_value').driver
        driver.expression='enabled * gain'
        for name,key in [('enabled',enable),('gain',gain)]:
            variable=driver.variables.new();variable.name=name;variable.type='SINGLE_PROP'
            variable.targets[0].id_type='SCENE';variable.targets[0].id=scene;variable.targets[0].data_path='["'+key+'"]'
        alpha=math_node('MULTIPLY',alpha,toggle.outputs[0])
        emission=nodes.new('ShaderNodeEmission');emission.inputs['Color'].default_value=(*color,1);emission.inputs['Strength'].default_value=1
        transparent=nodes.new('ShaderNodeBsdfTransparent');mix=nodes.new('ShaderNodeMixShader');output=nodes.new('ShaderNodeOutputMaterial')
        links.new(alpha,mix.inputs[0]);links.new(transparent.outputs[0],mix.inputs[1]);links.new(emission.outputs[0],mix.inputs[2]);links.new(mix.outputs[0],output.inputs['Surface'])
        obj.data.materials.append(mat)
    return {'kind':'optional analytic limb visualization','reference_utc':config['reference_utc'],'settings':config,
            'controls':[k for k,_,_ in controls],'satellite_texture_changed':False,'ocean_recolored':False,
            'is_measured_atmosphere':False,'source':'camera-ray limb profiles and UTC solar direction; not an airglow observation'}
