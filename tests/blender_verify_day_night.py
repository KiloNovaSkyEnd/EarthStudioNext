"""Real globe UV/color/availability checks for an integrated day/night surface."""
import json,math,runpy,sys
from pathlib import Path
import bpy
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from blender_make_earth import position_preview_camera


def main():
    helpers=runpy.run_path(str(ROOT/'tests/blender_verify.py'),run_name='shared_uv_helpers')
    ray_uv=helpers['ray_uv'];scene=bpy.context.scene
    assert scene['GES_flattened_day_night'] and not scene['GES_surface_is_placeholder']
    assert 'Observed_Satellite_Clouds' not in bpy.data.objects,'Do not pretend integrated day RGB is a retrieved cloud shell'
    earth=bpy.data.objects['Earth_Surface']
    tex=next(n.image for n in earth.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE')
    assert tex.packed_file is not None
    width,height=tex.size;values=np.empty(width*height*4,dtype=np.float32);tex.pixels.foreach_get(values)
    rgba=values.reshape(height,width,4)
    source=Path(scene['GES_source_texture']);folder=Path(bpy.data.filepath).parent
    def map_values(suffix):
        im=bpy.data.images.load(str(source.with_name(source.stem+'_'+suffix+'.png')),check_existing=False)
        a=np.empty(width*height*4,dtype=np.float32);im.pixels.foreach_get(a)
        result=a.reshape(height,width,4)[...,0].copy();bpy.data.images.remove(im);return result
    meta=json.loads(source.with_suffix('.json').read_text())
    context=meta.get('display_recipe') in ['observed-abi-rgb-static-context-v8','single-solar-rgb-ir-context-v9']
    day=map_values('observed_rgb_weight' if context else 'day_contribution')
    night=1-day if context else map_values('night_contribution')
    stable=np.ones((height,width),dtype=bool)
    for axis in [0,1]:
        for shift in [-1,1]:
            stable&=np.max(abs(np.roll(rgba,shift,axis)-rgba),axis=-1)<.035
    color_stable=stable.copy()
    stable[:height*2//9]=False;stable[-height*2//9:]=False
    probes=[('Day_Quito',-78.4678,-.1807),('Night_Taiwan',121.0,23.5)]
    masks=[('TwilightAvailability',(night>.15)&(night<.8)&(day==0)),
           ('MissingDayVIS',(day==0)&(night==0)&(rgba[...,3]==0)),
           ('DayTextureProbe',(day>.99)&(np.min(rgba[...,:3],axis=-1)>.7)),
           ('NightBlueTextureProbe',(night>.99)&(rgba[...,2]>rgba[...,0]+.035)&(rgba[...,0]>.02))]
    if context:
        masks[0]=('TwilightBlend',(day>.2)&(day<.8)&(night>.2)&(night<.8))
        masks[1]=('StaticReferenceOnly',map_values('static_reference_only')>.99)
    elif meta.get('display_recipe') in ['observed-rayleigh-day-measured-ir-fallback-v2','separate-ground-measured-vis-ir-c2-v4']:
        fallback=map_values('measured_ir_day_gap')
        masks[0]=('TwilightBlend',(day>.2)&(day<.8)&(night>.2)&(night<.8))
        masks[1]=('MeasuredDayIRFallback',fallback>.99)
    for name,mask in masks:
        candidates=np.argwhere(mask&(color_stable if name=='StaticReferenceOnly' else stable));assert len(candidates),name+' has no actual source sample'
        y,x=candidates[len(candidates)//2]
        probes.append((name,(x+.5)*360/width-180,(y+.5)*180/height-90))
    scene.render.resolution_x=513;scene.render.resolution_y=513;scene.render.resolution_percentage=100
    scene.render.film_transparent=True;report=[]
    for name,lon,lat in probes:
        uv,radius=ray_uv(earth,lon,lat);expected_uv=((lon+180)/360,(lat+90)/180)
        error=max(abs(uv[i]-expected_uv[i]) for i in [0,1]);assert error<6e-5
        sx,sy=uv.x*width-.5,uv.y*height-.5;x0,y0=math.floor(sx),math.floor(sy);fx,fy=sx-x0,sy-y0
        def sample(dx,dy):return rgba[min(height-1,max(0,y0+dy)),min(width-1,max(0,x0+dx))]
        expected=(1-fy)*((1-fx)*sample(0,0)+fx*sample(1,0))+fy*((1-fx)*sample(0,1)+fx*sample(1,1))
        position_preview_camera(scene.camera,lon,lat);scene.camera.data.lens=4000
        p=folder/(name.lower()+'_probe.png');scene.render.filepath=str(p);bpy.ops.render.render(write_still=True)
        rendered=bpy.data.images.load(str(p),check_existing=False)
        actual=np.array(rendered.pixels[4*(256*513+256):4*(256*513+256)+4])
        alpha_error=float(abs(actual[3]-expected[3]));assert alpha_error<.035,(name,actual,expected)
        rgb_error=float(abs(actual[:3]-expected[:3]).max()) if expected[3]>.05 else 0.0
        assert rgb_error<.05,(name,rgb_error,actual,expected)
        bpy.data.images.remove(rendered)
        report.append({'name':name,'longitude':lon,'latitude':lat,'uv_max_error':error,
            'source_rgba':expected.tolist(),'render_rgba':actual.tolist(),'max_rgb_error':rgb_error,
            'alpha_error':alpha_error,'earth_radius_km':radius})
    scene.render.film_transparent=False;scene.render.resolution_x=3840;scene.render.resolution_y=2160
    views=[('day_americas_4k.png',-75,15),('terminator_4k.png',5,10),('night_asia_4k.png',135,15)]
    if context or meta.get('display_recipe')=='separate-ground-measured-vis-ir-c2-v4':
        views += [('sunrise_pacific_4k.png',-155,0),('indian_ocean_4k.png',60,-15),('south_atlantic_4k.png',-10,-45)]
    if context:views += [('north_atlantic_4k.png',-35,55)]
    for name,lon,lat in views:
        position_preview_camera(scene.camera,lon,lat);scene.camera.data.lens=52
        scene.render.filepath=str(folder/name);bpy.ops.render.render(write_still=True)
    (folder/'verification.json').write_text(json.dumps({'passed':True,'checks':report,'packed_texture':True,
        'blender_version':bpy.app.version_string,'flat_surface_contains_observed_day_clouds':True,
        'limitations':('Source-to-render consistency only, not cloud truth. Opaque static reference in missing observations is checked separately and is NOT recovered cloud coverage.' if context else 'Source-to-render consistency only, not independent cloud truth. No day cloud optical-depth/height retrieval or global VIS coverage. V2 uses explicit measured IR for missing VIS; both missing stays transparent.')},indent=2),encoding='utf-8')
    print('DAY/NIGHT GLOBE VERIFIED',len(report),'UV/RGB/availability probes',flush=True)


if __name__=='__main__':main()
