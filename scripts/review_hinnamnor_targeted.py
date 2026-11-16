"""Separated cloud scope/tint, original-resolution lights, and physical ocean controls."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
import moderngl
from ges.storage import load_config
from ges.goni_film import NativeCloudRenderer
from ges.film_transition import load_reference
from ges.atmosphere_scattering import geographic
from ges.solar import sun_direction
from ges.catalog import utc_time
from scripts.review_hinnamnor_ocean import frame as old_frame,camera,SETTINGS,pair
from scripts.compare_hinnamnor_geocolor import sha
from scripts.audit_render_baseline import difference


def engine(width=1920,height=1080,night_width=4096):
    cfg=load_config()
    day,_=load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',4096,
                         'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night,meta=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',night_width,
                           'static reference night-lights composite, not contemporaneous with satellite clouds')
    assert night_width<=meta['width'],'Do not upsample and claim new detail'
    water=np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    r=NativeCloudRenderer(day,night,width,height,1,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
    return r


def expanded(stamp):
    cfg=load_config();src=cfg.processed_dir/'hinnamnor_targeted_v1'/stamp
    m=json.loads((src/'official_metadata.json').read_text());proj=m['projection'].copy();proj['b']=proj['a']*(1-1/proj['rf'])
    with np.load(src/'l2_observed_roi.npz') as f:
        ht,err=f['CldTopHght'],f['ZcError'];valid=np.isin(f['CloudMask'],[2,3])&(f['CloudMaskQualFlag']==0)&(f['CloudHgtQF']==0)
        valid&=np.isfinite(ht)&(ht>0)&(ht<=20000)&np.isfinite(err)&(err>=0)&(err<=3000)
        h=np.where(valid,ht/1000,np.nan).astype(np.float32)
    return src,h,{'projection':proj,'extent_m':m['area_extent_m']},m


def lights_and_sea(output_name='lights_sea'):
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_targeted_v1';out=root/output_name;out.mkdir(exist_ok=False)
    cam={'position':geographic(135,35,7971),'target':geographic(135,35,6371),'up':np.array([0.,0.,1.]),'fov':28}
    rgba,h,m,obs,src=old_frame('1130',True);sun=sun_direction(utc_time(obs['nominal_utc']));images={};metrics={}
    gpus=[]
    for resolution in [4096,13500]:
        r=engine(3840,2160,resolution)
        try:
            r.update(rgba,h,m)
            for cloudy in [False,True]:
                name=str(resolution)+('_cloudy' if cloudy else '_no_clouds')
                im=r.render(cam,sun,**{**SETTINGS,'clouds':cloudy});images[name]=im;Image.fromarray(im).save(out/(name+'.png'))
            r.textures[1].filter=(moderngl.LINEAR,moderngl.LINEAR)
            no_mip=r.render(cam,sun,**{**SETTINGS,'clouds':False})
            metrics[str(resolution)+'_no_mipmap_delta']=difference(images[str(resolution)+'_no_clouds'],no_mip)
            metrics[str(resolution)+'_saturated_pixel_fraction']=float(np.any(images[str(resolution)+'_no_clouds']==255,axis=-1).mean())
            r.textures[1].filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
            metrics['gpu']=r.device;metrics['maximum_texture_size']=r.ctx.info['GL_MAX_TEXTURE_SIZE']
            gpus.append(r.device)
            if resolution==13500:
                gain1=r.render(cam,sun,**{**SETTINGS,'clouds':False},city_light_gain=1.)
                Image.fromarray(gain1).save(out/'13500_gain1_no_clouds.png')
                Image.fromarray(gain1).crop((1400,600,2400,1400)).save(out/'crop_13500_gain1.png')
                pair(out/'lights_gain_only_pair.png',images['13500_no_clouds'],gain1,'Same source and GPU | LEFT gain2 / RIGHT gain1')
                metrics['gain1_saturated_pixel_fraction']=float(np.any(gain1==255,axis=-1).mean())
        finally:r.close()
    assert len(set(gpus))==1,'Resolution controls used different GPUs'
    metrics['control_gpus']=gpus
    pair(out/'lights_4k_pair.png',images['4096_no_clouds'],images['13500_no_clouds'],
         'Diagnostic cloud OFF | LEFT 4096 resample / RIGHT original 13500 | no sharpening or exposure gain')
    pair(out/'lights_actual_clouds_pair.png',images['4096_cloudy'],images['13500_cloudy'],
         'Actual 2022 AHI clouds, static 2016 lights | LEFT 4096 / RIGHT 13500')
    crop=(1400,600,2400,1400)
    for n,a in images.items():Image.fromarray(a).crop(crop).save(out/('crop_'+n+'.png'))
    # Sea diagnosis uses fixed old clouds and identical marine parameters. No
    # profile is promoted; surface shadows now obey the explicit cloud OFF.
    r=engine();cam=camera(True);rgba,h,m,obs,src=old_frame('0830',True);r.update(rgba,h,m);sun=sun_direction(utc_time(obs['nominal_utc']))
    try:
        cases={'on':{},'no_atmosphere':{'atmosphere':False},'no_clouds':{'clouds':False},
               'no_reflections':{'ocean_reflections':False},'deep_water_candidate':{'deep_ocean_material':True},
               'clear_no_atmosphere':{'clouds':False,'atmosphere':False,'airglow':False}}
        rendered={}
        for name,over in cases.items():
            im=r.render(cam,sun,**{**SETTINGS,**over});rendered[name]=im;Image.fromarray(im).save(out/('sea_'+name+'.png'))
        metrics['sea_whole_frame_differences']={n:difference(rendered['on'],v) for n,v in rendered.items() if n!='on'}
        for n in cases:
            if n!='on':pair(out/('sea_'+n+'_pair.png'),rendered['on'],rendered[n],'LEFT original sea / RIGHT '+n+' | one-factor diagnostic')
    finally:r.close()
    (out/'verification.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8');print('LIGHTS AND SEA READY',flush=True)


def clouds(output_name='render',material_name='candidate'):
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_targeted_v1';out=root/output_name;out.mkdir(exist_ok=False);r=engine();cam=camera();records=[]
    try:
        for stamp in ['1000','1130']:
            src,h,m,obs=expanded(stamp);sun=sun_direction(utc_time(obs['nominal_utc']));old_rgba,old_h,old_m,_,_=old_frame(stamp,True)
            r.update(old_rgba,old_h,old_m);old=r.render(cam,sun,**SETTINGS);Image.fromarray(old).save(out/(stamp+'_old.png'))
            variants={}
            paths={'uniform':material_name+'/uniform_legacy_colour_rgba.png','evidence':material_name+'/B_current_material_rgba.png'}
            if stamp=='1130':paths['expanded_legacy']='expanded_legacy/B_current_material_rgba.png'
            for name,file in paths.items():
                values=np.asarray(Image.open(src/file).convert('RGBA'));r.update(values,h,m);im=r.render(cam,sun,**SETTINGS)
                variants[name]=im;Image.fromarray(im).save(out/(stamp+'_'+name+'.png'))
            pair(out/(stamp+'_coverage_policy_pair.png'),old,variants['uniform'],'LEFT old crop/Goni ROI / RIGHT expanded observed L2 policy (see report for clear screen)')
            pair(out/(stamp+'_colour_only_pair.png'),variants['uniform'],variants['evidence'],'LEFT old tint / RIGHT measured BTD tint | identical alpha/geometry')
            pair(out/(stamp+'_before_after.png'),old,variants['evidence'],'LEFT existing / RIGHT cloud candidate | fixed lights4096, ocean, camera, exposure')
            a=np.asarray(Image.open(src/material_name/'uniform_legacy_colour_rgba.png'))
            b=np.asarray(Image.open(src/material_name/'B_current_material_rgba.png'))
            assert np.array_equal(a[...,3],b[...,3]);changed=np.any(a[...,:3]!=b[...,:3],axis=-1)
            with np.load(src/material_name/'material_layers.npz') as f:
                low=f['low_confidence'];supported=np.repeat(np.repeat(low>0,2,0),2,1)
                assert not np.any(changed&~supported),'Tint leaked outside qualified low support'
            record={'stamp':stamp,'gpu':r.device,'colour_only_alpha_exact':True,'tint_outside_low_support_changed':0,
                    'colour_changed_pixels':int(changed.sum()),'uniform_vs_evidence_render':difference(variants['uniform'],variants['evidence'])}
            if material_name=='screened_candidate':
                unscreened=np.asarray(Image.open(src/'candidate/B_current_material_rgba.png'))
                r.update(unscreened,h,m);control=r.render(cam,sun,**SETTINGS)
                pair(out/(stamp+'_clear_only_pair.png'),control,variants['evidence'],'Same expanded data/tint | LEFT nonzero probability on clear / RIGHT QF0 clear screen')
                record['clear_screen_render_difference']=difference(control,variants['evidence'])
            if stamp=='1130':
                # Data expansion is checked on precisely the old source footprint.
                legacy=np.asarray(Image.open(src/'expanded_legacy/B_current_material_rgba.png'))
                common=legacy[:2300,600:3600]
                # Old inward_feather padded the old source boundary itself;
                # expanding actual coverage legitimately changes that 2px edge.
                assert np.array_equal(common[4:-4,4:-4],old_rgba[4:-4,4:-4]),'Expanded legacy interior differs'
                record['expanded_legacy_common_interior_exact']=True
                record['old_crop_edge_changed_pixels']=int(np.any(common!=old_rgba,axis=-1).sum())
            r.update(b,h,m);on=r.render(cam,sun,**SETTINGS)
            for effect,over in [('atmosphere',{'atmosphere':False}),('airglow',{'airglow':False}),('city_lights',{'city_lights':False})]:
                off=r.render(cam,sun,**{**SETTINGS,**over});pair(out/(stamp+'_'+effect+'_pair.png'),off,on,'Candidate '+effect+' OFF / ON')
                record[effect+'_contribution']=difference(on,off)
            # Actual oblique control, not a cure for remaining height/side streaks.
            side=r.render(camera(True),sun,**SETTINGS);Image.fromarray(side).save(out/(stamp+'_oblique.png'))
            records.append(record);print('CLOUD RENDER READY',stamp,flush=True)
    finally:r.close()
    (out/'verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lights-sea',action='store_true');p.add_argument('--output-name');p.add_argument('--material-name',default='candidate');a=p.parse_args()
    lights_and_sea(a.output_name or 'lights_sea') if a.lights_sea else clouds(a.output_name or 'render',a.material_name)
