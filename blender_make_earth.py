"""Blender 4.x/5.x script: import real equirectangular cloud PNG onto globe.
Run: blender --background --python blender_make_earth.py -- --cloud PATH --earth PATH --out PATH
No generated cloud pixels. Creates only geometry, material and static preview camera.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys


def args_after_double_dash():
    parser = argparse.ArgumentParser(description='Create static globe scene with measured satellite cloud texture')
    parser.add_argument('--cloud',required=True,help='Equirectangular 2:1 RGBA cloud image produced by GES')
    parser.add_argument('--earth',default='',help='Optional NASA Blue Marble 2:1 equirectangular Earth surface texture')
    parser.add_argument('--night-reference',default='',help='Prepared static night surface from ges night (not contemporaneous observations)')
    parser.add_argument('--out',default='earth_scene.blend')
    parser.add_argument('--preview',default='',help='Optional static render PNG')
    parser.add_argument('--preview-width',type=int,choices=[1920,3840],default=1920)
    parser.add_argument('--diagnostic',action='store_true',help='Unlit data inspection, not a cinematic cloud material')
    parser.add_argument('--atmosphere-config',default='',help='Optional explicitly synthetic atmosphere JSON; default is no atmosphere effects')
    tail = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    return parser.parse_args(tail)


def geographic_position(longitude, latitude, radius):
    lon, lat = math.radians(longitude), math.radians(latitude)
    return (radius * math.cos(lat) * math.cos(lon),
            radius * math.cos(lat) * math.sin(lon), radius * math.sin(lat))


def validate_cloud(path):
    """Validate GES RGBA/global-grid contract before modifying a Blender scene."""
    with path.open('rb') as source:
        header = source.read(33)
    if len(header) != 33 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise ValueError('Cloud texture must be a PNG')
    width, height = struct.unpack('>II', header[16:24])
    if header[25] != 6 or width != 2 * height or height == 0:
        raise ValueError('Cloud texture must be 2:1 RGBA PNG')
    meta = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if str(meta.get('validation_status','')).startswith('REJECTED'):
        raise ValueError('Texture failed source validation; use its corrected replacement')
    if (meta.get('projection') != 'EPSG:4326'
            or meta.get('extent_wsen') != [-180, -90, 180, 90]
            or (meta.get('width'), meta.get('height')) != (width, height)):
        raise ValueError('Cloud provenance must match the global PNG grid')
    return meta


def position_preview_camera(camera, longitude=135.0, latitude=15.0):
    """One fixed inspection view; no camera timeline or cinematic editor."""
    from mathutils import Vector
    position = Vector(geographic_position(longitude, latitude, 40000))
    camera.location = position
    camera.rotation_euler = (-position).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = 'PERSP'
    camera.data.lens = 52
    # Keep a tight enough depth range to separate the 12 km shell from surface
    # at kilometer scene scale (near=1 caused visible depth-buffer fighting).
    camera.data.clip_start = 1000
    camera.data.clip_end = 100000


def validate_output_paths(cloud, earth, outfile, preview):
    inputs = {cloud.resolve(), cloud.with_suffix('.json').resolve()}
    if earth:
        inputs.add(earth.resolve())
        inputs.add(earth.with_suffix('.json').resolve())
    outputs = {outfile.resolve(), outfile.with_suffix('.json').resolve()}
    if preview:
        if preview.resolve() in outputs:
            raise ValueError('Preview conflicts with scene output')
        outputs.add(preview.resolve())
    if inputs & outputs:
        raise ValueError('Scene outputs must not overwrite input textures or provenance')


def make_geo_sphere(name, radius, nlon=180, nlat=90):
    import bpy
    from mathutils import Vector
    verts = []
    uvs = []
    for j in range(nlat+1):
        lat=-90+180*j/nlat
        r=radius*math.cos(math.radians(lat))
        z=radius*math.sin(math.radians(lat))
        for i in range(nlon+1):
            lon=-180+360*i/nlon
            verts.append((r*math.cos(math.radians(lon)),r*math.sin(math.radians(lon)),z))
            uvs.append((i/nlon,j/nlat))
    faces=[]
    for j in range(nlat):
        for i in range(nlon):
            k=j*(nlon+1)+i
            faces.append((k,k+1,k+1+(nlon+1),k+(nlon+1)))
    mesh=bpy.data.meshes.new(name+'_mesh')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv_layer=mesh.uv_layers.new(name='Equirectangular_WGS84')
    for poly in mesh.polygons:
        poly.use_smooth=True
        for li in poly.loop_indices:
            uv_layer.data[li].uv=uvs[mesh.loops[li].vertex_index]
    obj=bpy.data.objects.new(name,mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def texture_material(name, path, transparent=False, diagnostic=False):
    import bpy
    material=bpy.data.materials.new(name)
    material.use_nodes=True
    bsdf=material.node_tree.nodes.get('Principled BSDF')
    img=bpy.data.images.load(str(path), check_existing=True)
    img.alpha_mode='STRAIGHT'
    tex=material.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image=img
    tex.interpolation='Linear'
    # Longitude is supplied by our mesh UV, not Blender's generated coordinates.
    uv=material.node_tree.nodes.new('ShaderNodeUVMap')
    uv.uv_map='Equirectangular_WGS84'
    material.node_tree.links.new(uv.outputs['UV'],tex.inputs['Vector'])
    material.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value=1
    if transparent:
        material.use_backface_culling=True
        material.node_tree.links.new(tex.outputs['Alpha'],bsdf.inputs['Alpha'])
        if hasattr(material,'surface_render_method'):
            material.surface_render_method='BLENDED' if diagnostic else 'DITHERED'
        elif hasattr(material,'blend_method'):
            material.blend_method='BLEND'
    if diagnostic:
        # Data inspection only: preserve IR display values independent of sun.
        nodes=material.node_tree.nodes
        emission=nodes.new('ShaderNodeEmission')
        material.node_tree.links.new(tex.outputs['Color'],emission.inputs['Color'])
        output=nodes.get('Material Output')
        if transparent:
            clear=nodes.new('ShaderNodeBsdfTransparent')
            mix=nodes.new('ShaderNodeMixShader')
            material.node_tree.links.new(tex.outputs['Alpha'],mix.inputs[0])
            material.node_tree.links.new(clear.outputs[0],mix.inputs[1])
            material.node_tree.links.new(emission.outputs[0],mix.inputs[2])
            material.node_tree.links.new(mix.outputs[0],output.inputs['Surface'])
        else:
            material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
    return material


def main():
    import bpy
    from mathutils import Vector
    args=args_after_double_dash()
    cloud=Path(args.cloud).expanduser().resolve()
    if not cloud.is_file():
        raise FileNotFoundError(f'Cloud observation texture not found: {cloud}')
    if cloud.suffix.lower() != '.png':
        raise ValueError('Cloud must be RGBA PNG from GES render/mosaic')
    provenance=validate_cloud(cloud)
    atmosphere=None
    if args.atmosphere_config:
        atmosphere=json.loads(Path(args.atmosphere_config).read_text(encoding='utf-8'))
        stamp=provenance.get('reference_utc') or provenance.get('observed_utc')
        if atmosphere.get('kind')!='optional atmosphere visualization, NOT measured atmosphere' or atmosphere.get('reference_utc')!=stamp:
            raise ValueError('Explicit atmosphere visualization with matching source UTC required')
        v=atmosphere['sun_direction_ecef']
        if len(v)!=3 or not all(math.isfinite(x) for x in v) or abs(sum(x*x for x in v)-1)>1e-5:
            raise ValueError('Finite Earth-fixed unit solar direction required')
        for key,low,high in [('day_strength',0,1),('airglow_strength',0,1),('day_width_km',1,50),
            ('airglow_height_km',70,110),('airglow_width_km',1,20),('shell_height_km',115,150)]:
            if not math.isfinite(atmosphere[key]) or not low<=atmosphere[key]<=high:raise ValueError('Invalid atmosphere '+key)
        for key in ['day_linear_rgb','airglow_linear_rgb']:
            if len(atmosphere[key])!=3 or any(not math.isfinite(x) or not 0<=x<=1 for x in atmosphere[key]):
                raise ValueError('Invalid atmosphere display RGB')
    flattened=provenance.get('product')=='day-night-display'
    if flattened:
        if args.earth or args.night_reference:raise ValueError('Integrated day/night surface already contains observed surface/clouds and documented night reference')
        args.diagnostic=True
    night_provenance=None
    if args.night_reference:
        if args.earth or provenance.get('product') != 'ir-night-display':
            raise ValueError('Night reference requires prepared ir-night-display and no --earth')
        args.diagnostic=True
        night_path=Path(args.night_reference).expanduser().resolve()
        night_provenance=json.loads(night_path.with_suffix('.json').read_text(encoding='utf-8'))
        if (night_provenance.get('kind') != 'static night reference with computed solar gating and missing-IR tint'
                or night_provenance.get('projection') != 'EPSG:4326'
                or night_provenance.get('extent_wsen') != [-180,-90,180,90]
                or night_provenance.get('width') != provenance['width']
                or night_provenance.get('height') != provenance['height']
                or night_provenance.get('model_utc') != (provenance.get('reference_utc') or provenance.get('observed_utc'))):
            raise ValueError('Night reference grid/model UTC differs from cloud display')
    outfile=Path(args.out).expanduser().resolve()
    preview=Path(args.preview).expanduser().resolve() if args.preview else None
    if outfile.suffix.lower() != '.blend' or (preview and preview.suffix.lower() != '.png'):
        raise ValueError('Scene output must be .blend and preview must be .png')
    earth=night_path if args.night_reference else Path(args.earth).expanduser().resolve() if args.earth else None
    if earth and not earth.is_file():
        raise FileNotFoundError(f'Earth base map not found: {earth}')
    validate_output_paths(cloud, earth, outfile, preview)
    if args.atmosphere_config and Path(args.atmosphere_config).resolve() in {outfile,outfile.with_suffix('.json'),preview}:
        raise ValueError('Do not overwrite the atmosphere configuration input')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    base=make_geo_sphere('Earth_Surface',6371,180,90)
    if flattened:
        base.data.materials.append(texture_material('Observed day RGB and night IR integrated surface',cloud,transparent=True,diagnostic=True))
    elif earth:
        base.data.materials.append(texture_material('Static VIIRS 2016 night reference' if args.night_reference else
                                                   'NASA Earth Surface (user supplied)',earth,
                                                   diagnostic=bool(args.night_reference)))
    else:
        mat=bpy.data.materials.new('PLACEHOLDER surface - supply NASA Blue Marble')
        mat.diffuse_color=(0.016,0.08,0.13,1)
        mat.use_nodes=True
        shader=mat.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value=mat.diffuse_color
        shader.inputs['Roughness'].default_value=1
        if args.diagnostic:
            emission=mat.node_tree.nodes.new('ShaderNodeEmission')
            emission.inputs['Color'].default_value=mat.diffuse_color
            mat.node_tree.links.new(emission.outputs[0],
                                   mat.node_tree.nodes.get('Material Output').inputs['Surface'])
        base.data.materials.append(mat)
    if not flattened:
        clouds=make_geo_sphere('Observed_Satellite_Clouds',6371+12,240,120)
        clouds.data.materials.append(texture_material('Observed IR data diagnostic' if args.diagnostic else
                                                    'Real Satellite RGBA Texture',cloud,
                                                    transparent=True,diagnostic=args.diagnostic))
    sun_data=bpy.data.lights.new('Preview_Sun_NOT_TIME_CALIBRATED','SUN')
    sun=bpy.data.objects.new('Preview_Sun_NOT_TIME_CALIBRATED',sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler=(math.radians(20),math.radians(-35),math.radians(-30))
    sun_data.energy=2.0
    # Static inspection camera only. No cinematic trajectory is invented here.
    bpy.ops.object.camera_add()
    cam=bpy.context.object
    cam.name='Static_Preview_Camera'
    position_preview_camera(cam)
    bpy.context.scene.camera=cam
    scene=bpy.context.scene
    scene.render.resolution_x=args.preview_width
    scene.render.resolution_y=args.preview_width * 9 // 16
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGBA'
    if args.diagnostic:
        scene.view_settings.view_transform='Standard'
    scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(0,0,0,1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=0
    if hasattr(scene,'render') and 'BLENDER_EEVEE_NEXT' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]:
        scene.render.engine='BLENDER_EEVEE_NEXT'
    # Reopen without fragile absolute references by packing images.
    bpy.ops.file.pack_all()
    outfile.parent.mkdir(parents=True,exist_ok=True)
    if preview:
        preview.parent.mkdir(parents=True,exist_ok=True)
        scene.render.filepath=str(preview)
    scene['GES_source_texture']=str(cloud)
    scene['GES_diagnostic']=args.diagnostic
    scene['GES_night_display']=bool(args.night_reference)
    scene['GES_surface_is_placeholder']=not bool(earth) and not flattened
    scene['GES_flattened_day_night']=flattened
    scene['GES_cloud_shell_height_km_approximation']=0.0 if flattened else 12.0
    scene['GES_historical_sun_calibrated']=False
    effect_provenance=None
    if atmosphere:
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from blender_atmosphere import install_atmosphere
        effect_provenance=install_atmosphere(scene,atmosphere,make_geo_sphere)
    bpy.ops.wm.save_as_mainfile(filepath=str(outfile))
    outfile.with_suffix('.json').write_text(json.dumps({
        'kind':'observed day/night integrated surface preview' if flattened else
               'IR night visualization (opacity approximation)' if args.night_reference else
               'static diagnostic globe' if args.diagnostic else 'static preview globe',
        'blender_version':bpy.app.version_string, 'source_texture':str(cloud),
        'source_sha256':hashlib.sha256(cloud.read_bytes()).hexdigest(),
        'source_provenance':provenance, 'surface_is_placeholder':not bool(earth) and not flattened,
        'night_reference_provenance':night_provenance,
        'optional_atmosphere':effect_provenance,
        'cloud_shell_height_km_approximation':0 if flattened else 12, 'historical_sun_calibrated':False,
        'texture_sampling':'linear; explicit Equirectangular_WGS84 UV',
        'preview':str(preview) if preview else None,
        'notes':('Flattened observed daytime RGB + measured twilight/night IR with independent static night reference. Computed UTC solar selection; unlit display, no cloud heights/volume.' if flattened else
                'IR display opacity is not a cloud mask or measured optical thickness/height. '
                'Night lights, when supplied, are an independent static reference. '
                'No volume clouds or true RGB/IR day/night image composition.'),
    },indent=2),encoding='utf-8')
    if preview:
        bpy.ops.render.render(write_still=True)
    print('Created scene: ',outfile)
    print('UTC solar selection is baked into the integrated image; unlit preview, no 3D sunlight/cloud-height model.' if flattened else
          'Warning: Sun is fixed preview-only. Do not imply physical historical sunlight until UTC solar geometry is added.')

if __name__=='__main__':
    main()
