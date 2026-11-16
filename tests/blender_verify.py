"""Run with Blender --background earth_diagnostic.blend --python this_file.

Actual Blender mesh/ray/UV and render-alpha verification; no generated cloud
pixels. Writes three static views and a machine-readable report beside scene.
"""
from pathlib import Path
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blender_make_earth import geographic_position, position_preview_camera


def ray_uv(obj, longitude, latitude):
    normal = Vector(geographic_position(longitude, latitude, 1))
    hit, point, face_normal, face = obj.ray_cast(normal * 30000, -normal)
    assert hit, 'Geographic ray missed the globe'
    assert face_normal.dot(normal) > .99, 'Inverted globe normal'
    mesh = obj.data
    mesh.calc_loop_triangles()
    layer = mesh.uv_layers['Equirectangular_WGS84']
    for tri in mesh.loop_triangles:
        if tri.polygon_index != face:
            continue
        a, b, c = [mesh.vertices[index].co for index in tri.vertices]
        v0, v1, v2 = b - a, c - a, point - a
        d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
        divisor = d00 * d11 - d01 * d01
        if abs(divisor) < 1e-8:
            continue
        v = (d11 * v2.dot(v0) - d01 * v2.dot(v1)) / divisor
        w = (d00 * v2.dot(v1) - d01 * v2.dot(v0)) / divisor
        u = 1 - v - w
        if min(u, v, w) < -1e-4:
            continue
        uv = sum((layer.data[loop].uv * weight
                  for loop, weight in zip(tri.loops, (u, v, w))), Vector((0, 0)))
        return uv, point.length
    raise AssertionError('Could not interpolate the ray-hit triangle UV')


def main():
    scene = bpy.context.scene
    assert scene['GES_diagnostic'], 'Use an unlit diagnostic scene for these checks'
    clouds = bpy.data.objects['Observed_Satellite_Clouds']
    base = bpy.data.objects['Earth_Surface']
    tex = next(n.image for n in clouds.data.materials[0].node_tree.nodes
               if n.type == 'TEX_IMAGE')
    assert tex.packed_file is not None, 'Scene texture was not packed'
    width, height = tex.size
    pixels = np.empty(width * height * 4,dtype=np.float32)
    tex.pixels.foreach_get(pixels)
    night_display=bool(scene.get('GES_night_display',False))
    coverage_tex=None
    if night_display:
        source=Path(scene['GES_source_texture'])
        meta=json.loads(source.with_suffix('.json').read_text())
        coverage_tex=bpy.data.images.load(str(source.parent/meta['source_ir_coverage']))
    folder = Path(bpy.data.filepath).parent
    (folder / 'verification.json').unlink(missing_ok=True)
    scene.render.resolution_x = 513
    scene.render.resolution_y = 513
    scene.render.resolution_percentage = 100
    report = []
    goes_only='--goes-only' in sys.argv
    probes=[('Tokyo',139.6917,35.6895,0 if goes_only else 1),
                                           ('Quito',-78.4678,-.1807,0 if '--himawari-only' in sys.argv else 1),
                                           ('Nairobi',36.8219,-1.2921,1 if '--nairobi-covered' in sys.argv else 0)]
    if night_display:
        texture_values=pixels.reshape(height,width,4)
        stable=(texture_values[...,3]>.35)&(texture_values[...,2]>texture_values[...,0]+.04)
        if not stable.any():stable=texture_values[...,3]>.5
        for axis in [0,1]:
            stable&=(abs(np.roll(texture_values[...,3],1,axis)-texture_values[...,3])<.04)
            stable&=(abs(np.roll(texture_values[...,3],-1,axis)-texture_values[...,3])<.04)
        stable[:height//6]=False;stable[-height//6:]=False
        candidates=np.argwhere(stable)
        if len(candidates):
            py,px=candidates[len(candidates)//2]
            probes.append(('CloudTextureProbe',(px+.5)*360/width-180,(py+.5)*180/height-90,1))
        weak=(texture_values[...,3]>.05)&(texture_values[...,3]<.25)&(texture_values[...,2]>texture_values[...,0]+.04)
        for axis in [0,1]:
            for shift in [-1,1]:
                weak&=abs(np.roll(texture_values[...,3],shift,axis)-texture_values[...,3])<.01
                weak&=abs(np.roll(texture_values[...,0],shift,axis)-texture_values[...,0])<.04
        weak[:height//6]=False;weak[-height//6:]=False
        candidates=np.argwhere(weak)
        if len(candidates):
            py,px=candidates[len(candidates)//2]
            probes.append(('WeakCloudTextureProbe',(px+.5)*360/width-180,(py+.5)*180/height-90,1))
    for name, lon, lat, expected_alpha in probes:
        uv, radius = ray_uv(clouds, lon, lat)
        expected_uv = ((lon + 180) / 360, (lat + 90) / 180)
        error = max(abs(uv[i] - expected_uv[i]) for i in (0,1))
        assert error < 3e-5, f'{name}: wrong longitude/latitude UV: {list(uv)}'
        _, surface_radius = ray_uv(base, lon, lat)
        assert radius - surface_radius > 10, 'Cloud shell intersects the surface'
        x, y = min(width-1,int(uv.x * width)), min(height-1,int(uv.y * height))
        alpha = pixels[4 * (y * width + x) + 3]  # Blender rows start at south.
        if night_display:
            genuine_coverage=coverage_tex.pixels[4 * (y * width + x)]
            if '--coverage-from-texture' in sys.argv:
                # For new footprints this checks material/UV consistency;
                # independent geographic footprint expectation is not claimed.
                expected_alpha=genuine_coverage
            assert abs(genuine_coverage-expected_alpha)<1e-6, f'{name}: genuine coverage differs'
            if expected_alpha == 0:
                assert alpha == 0, 'Missing observation acquired display opacity'
            # The material linearly filters the RGBA texture. A nearest texel
            # is not the expected rendered alpha across sharp spectral edges.
            sx,sy=uv.x*width-.5,uv.y*height-.5
            x0,y0=math.floor(sx),math.floor(sy)
            fx,fy=sx-x0,sy-y0
            def tex_alpha(dx,dy):
                xx=min(width-1,max(0,x0+dx)); yy=min(height-1,max(0,y0+dy))
                return float(pixels[4*(yy*width+xx)+3])
            expected_alpha=((1-fy)*((1-fx)*tex_alpha(0,0)+fx*tex_alpha(1,0))
                            +fy*((1-fx)*tex_alpha(0,1)+fx*tex_alpha(1,1)))
        else:
            assert abs(alpha - expected_alpha) < 1e-6, f'{name}: source coverage differs'
        position_preview_camera(scene.camera, lon, lat)
        base.hide_render = False
        scene.render.film_transparent = False
        scene.render.filepath = str(folder / (name.lower() + '_view.png'))
        bpy.ops.render.render(write_still=True)
        # Hide the surface to test actual material alpha, including backfaces.
        base.hide_render = True
        scene.render.film_transparent = True
        original_lens=scene.camera.data.lens
        # A whole-globe 513px render integrates many 8K texels per pixel.
        # Magnify the alpha probe so it tests local shader/UV transparency.
        scene.camera.data.lens=4000
        alpha_path = folder / (name.lower() + '_alpha.png')
        scene.render.filepath = str(alpha_path)
        bpy.ops.render.render(write_still=True)
        rendered = bpy.data.images.load(str(alpha_path), check_existing=False)
        center_alpha = rendered.pixels[4 * (256 * 513 + 256) + 3]
        color_report={}
        if name.endswith('CloudTextureProbe'):
            actual_rgb=np.array(rendered.pixels[4*(256*513+256):4*(256*513+256)+3])
            expected_rgb=pixels[4*(y*width+x):4*(y*width+x)+3]
            color_error=float(abs(actual_rgb-expected_rgb).max())
            assert color_error<.04, f'Cloud RGB changed on globe: error={color_error}'
            color_report={'texture_rgb':expected_rgb.tolist(),'render_rgb':actual_rgb.tolist(),'max_rgb_error':color_error}
        scene.camera.data.lens=original_lens
        assert abs(center_alpha - expected_alpha) < .03, f'{name}: rendered alpha {center_alpha}, expected {expected_alpha}'
        bpy.data.images.remove(rendered)
        report.append({'name':name,'longitude':lon,'latitude':lat,'uv':list(uv),
                       'expected_uv':list(expected_uv),'uv_max_error':error,
                       'source_alpha':float(alpha),'render_center_alpha':center_alpha,
                       'cloud_surface_separation_km':radius-surface_radius,
                       'view':name.lower()+'_view.png','alpha_view':alpha_path.name,**color_report})
    if night_display:
        base.hide_render=False
        scene.render.film_transparent=False
        custom_view='--view-longitude' in sys.argv
        view_lon=float(sys.argv[sys.argv.index('--view-longitude')+1]) if custom_view else (-90 if goes_only else 130)
        view_lat=float(sys.argv[sys.argv.index('--view-latitude')+1]) if custom_view else (25 if goes_only else 20)
        position_preview_camera(scene.camera,view_lon,view_lat)
        scene.camera.data.lens=145
        scene.render.resolution_x=3840
        scene.render.resolution_y=2160
        scene.render.filepath=str(folder/('night_regional_closeup.png' if custom_view else 'night_americas_closeup.png' if goes_only else 'night_pacific_closeup.png'))
        bpy.ops.render.render(write_still=True)
    (folder / 'verification.json').write_text(json.dumps({
        'blender_version':bpy.app.version_string,'scene':Path(bpy.data.filepath).name,
        'packed_texture':True,'checks':report,'passed':True,
        'night_display':night_display,
        'footprint_expectation':'sampled source coverage, not independent footprint check' if '--coverage-from-texture' in sys.argv else 'fixed known geographic coverage probes',
        'limitations':'Coordinate/coverage diagnostic; display opacity is approximate. '
                      'Any night lights are static reference. No cloud height retrieval '
                      'or full RGB/IR day-night composition. Views are static.',
    },indent=2),encoding='utf-8')
    print(f'BLENDER VERIFICATION: {len(report)} geographic/texture UV + render-alpha checks passed')


if __name__ == '__main__':
    main()
