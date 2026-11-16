"""Isolated research shader, real monthly Rrs probe; never edit production shader."""
import json
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.goni_film import NativeCloudRenderer
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.audit_render_baseline import difference
from scripts.review_hinnamnor_ocean import frame, camera

ROOT=Path(__file__).resolve().parents[1]


def analysis_class(out):
    original=(ROOT/'ges/shaders/goni_film.frag').read_text()
    probe=original.replace('uniform sampler2D ocean_mask;', '''uniform sampler2D ocean_mask;
uniform sampler2D actual_water_probe;
uniform vec4 actual_water_uv;
uniform bool actual_water_enabled;
uniform int ocean_analysis_component;''')
    injection='''        float actual_water_weight=0.;
        if(actual_water_enabled){
            vec2 q=(uv-actual_water_uv.xy)/actual_water_uv.zw;
            if(all(greaterThanEqual(q,vec2(0.)))&&all(lessThanEqual(q,vec2(1.)))){
                vec4 measured=textureGrad(actual_water_probe,q,ux/actual_water_uv.zw,uy/actual_water_uv.zw);
                vec2 edge=min(q,1.-q)*actual_water_uv.zw*vec2(360.,180.);
                actual_water_weight=measured.a*smoothstep(0.,1.,min(edge.x,edge.y))*c2(.104528,.25,mu);
                if(measured.a>.00001)water_diffuse=mix(water_diffuse,measured.rgb/measured.a,actual_water_weight);
            }
        }
'''
    anchor='        if(!ocean_reflections_enabled){sky=vec3(0.);spec=0.;}'
    assert anchor in probe;probe=probe.replace(anchor,injection+anchor)
    anchor='        result=mix(result,sea,water);'
    probe=probe.replace(anchor,'''        if(ocean_analysis_component==1)return water*water_diffuse;
        if(ocean_analysis_component==2)return water*water_diffuse*(.001+.018*sky_day+.60*nl*shadow)*(1.-fresnel);
        if(ocean_analysis_component==3)return water*(sky*fresnel+incident*spec*shadow);
        if(ocean_analysis_component==4)return vec3(water*actual_water_weight);
'''+anchor)
    probe=probe.replace('    return result;','    if(ocean_analysis_component>0)return vec3(0.);\n    return result;')
    anchor='    vec2 top=roots(camera_position,ray,R+8.4);'
    probe=probe.replace(anchor,'    if(ocean_analysis_component>0){frag_color=vec4(clamp(srgb(base),0.,1.),1.);return;}\n'+anchor)
    (out/'ocean_analysis_only.frag').write_text(probe,encoding='utf-8')
    code=(ROOT/'ges/goni_film.py').read_text()
    anchor="(Path(__file__).parent/'shaders/goni_film.frag').read_text()"
    assert anchor in code;code=code.replace(anchor,'PROBE_FRAGMENT')
    module=types.ModuleType('ges._ocean_optics_analysis');module.__package__='ges';module.__file__=str(ROOT/'ges/goni_film.py');module.PROBE_FRAGMENT=probe
    sys.modules[module.__name__]=module;exec(compile(code,module.__file__,'exec'),module.__dict__)
    return module.NativeCloudRenderer


def pair(path,a,b,label):
    c=Image.new('RGB',(a.shape[1]*2,a.shape[0]+32),'#101722');c.paste(Image.fromarray(a),(0,32));c.paste(Image.fromarray(b),(a.shape[1],32));ImageDraw.Draw(c).text((8,8),label,fill='white');c.save(path)


def main():
    out=ROOT/'data/processed/hinnamnor_ocean_research_v2';dest=out/'renders';dest.mkdir(exist_ok=False);cfg=load_config()
    Probe=analysis_class(out)
    day,_=load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',4096,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night,_=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',13500,'static reference night-lights composite, not contemporaneous with satellite clouds')
    accepted=cfg.processed_dir/'hinnamnor_lights_v1/detail'
    lights=np.load(accepted/'east_asia_2016_500m.npy',mmap_mode='r');lm=json.loads((accepted/'east_asia_2016_500m.json').read_text())
    water=np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    have_rrs=(out/'rrs_rgb_equivalent_probe.npy').exists()
    raw=np.load(out/'rrs_rgb_equivalent_probe.npy') if have_rrs else np.zeros((2,2,4),np.float32)
    rm=json.loads((out/'rrs_probe_metadata.json').read_text()) if have_rrs else None
    rgba,h,m,obs,_=frame('0830',True);sun=sun_direction(utc_time(obs['nominal_utc']))
    settings=dict(exposure=1.,city_light_gain=.75,height_scale=.4,thickness=.8,volume_samples=96)
    r=Probe(day,night,1920,1080,1,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
    r.set_night_detail(lights,lm['extent_wsen']);r.update(rgba,h,m)
    with r.ctx:
        tex=r.ctx.texture((raw.shape[1],raw.shape[0]),4,np.ascontiguousarray(raw,np.float32).tobytes(),dtype='f4');tex.repeat_x=False;tex.repeat_y=False;tex.build_mipmaps();tex.anisotropy=16;tex.use(6)
        import moderngl
        tex.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
        r.program['actual_water_probe'].value=6;r.program['actual_water_enabled'].value=False;r.program['ocean_analysis_component'].value=0
        if rm:
            w,s,e,n=rm['extent_wsen'];r.program['actual_water_uv'].value=((w+180)/360,(90-n)/180,(e-w)/360,(n-s)/180)
    records={};profiles=['legacy','previous_constant']+(['real_rrs_probe'] if have_rrs else [])
    cases={'complete':{},'without_clouds':dict(clouds=False),'without_atmosphere':dict(atmosphere=False),'surface_only':dict(clouds=False,atmosphere=False,airglow=False)}
    try:
        # An analysis-only derivative must preserve the production image when disabled.
        q=NativeCloudRenderer(day,night,1920,1080,1,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
        try:
            q.set_night_detail(lights,lm['extent_wsen']);q.update(rgba,h,m)
            expected=q.render(camera(),sun,**settings);actual=r.render(camera(),sun,**settings)
            exact=difference(expected,actual);assert exact['max_dn']==0,exact
            records['disabled_analysis_vs_production']=exact;assert q.device==r.device
        finally:q.close()
        for view,cam in [('near',camera()),('oblique',camera(True))]:
            images={}
            for profile in profiles:
                with r.ctx:r.program['actual_water_enabled'].value=profile=='real_rrs_probe'
                for case,changes in cases.items():
                    values=r.render(cam,sun,**settings,deep_ocean_material=profile=='previous_constant',**changes)
                    images[(profile,case)]=values;Image.fromarray(values).save(dest/f'{view}_{profile}_{case}.png')
                for component in range(1,5):
                    with r.ctx:r.program['ocean_analysis_component'].value=component
                    values=r.render(cam,sun,**settings,deep_ocean_material=profile=='previous_constant',clouds=False)
                    Image.fromarray(values).save(dest/f'{view}_{profile}_component{component}.png')
                with r.ctx:r.program['ocean_analysis_component'].value=0
                print('READY',view,profile,r.device,flush=True)
            for profile in profiles[1:]:
                for case in cases:
                    a=images[('legacy',case)];b=images[(profile,case)]
                    pair(dest/f'{view}_{profile}_{case}_pair.jpg',a,b,'Same real AHI0830, camera, exposure1, accepted high-res lights | LEFT current / RIGHT '+profile+' (research only)')
                    records[f'{view}_{profile}_{case}']=difference(a,b)
        if have_rrs:
            nr,nh,nm,no,_=frame('1130',True);r.update(nr,nh,nm);nsun=sun_direction(utc_time(no['nominal_utc']))
            with r.ctx:r.program['actual_water_enabled'].value=False
            a=r.render(camera(),nsun,**settings)
            with r.ctx:r.program['actual_water_enabled'].value=True
            b=r.render(camera(),nsun,**settings)
            records['real_night_probe_delta']=difference(a,b);assert np.array_equal(a,b),'Day-only probe affected night'
            Image.fromarray(a).save(dest/'night_1130_source_off.png');Image.fromarray(b).save(dest/'night_1130_source_on.png')
        records.update(gpu=r.device,actual_rrs_available=have_rrs,weather_utc=obs['nominal_utc'],light_source='Accepted2016 500m region, global fallback',city_gain=.75,
            component_legend={'1':'linear material RGB-equivalent displayed in sRGB','2':'diffuse after fixed lighting/Fresnel, cloud shadows OFF','3':'reflected sky and bounded specular','4':'actual regional probe display weight'},
            limits='Temporary research shader only. Monthly3-band Rrs proxy is NOT validated true colour/BSDF or instantaneous water state. No new procedural texture, no production shader edits.')
        (out/'render_verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    finally:
        with r.ctx:tex.release()
        r.close()


if __name__=='__main__':main()
