"""Single-variable real night-reference comparisons and four scene stages."""
import argparse
import json
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image, ImageDraw

from ges.atmosphere_scattering import geographic
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.goni_film import NativeCloudRenderer
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.audit_render_baseline import difference
from scripts.review_hinnamnor_targeted import expanded

ROOT=Path(__file__).resolve().parents[1]
VIEWS={'east_china':(119.,32.),'japan':(137.,36.),'korea':(127.5,37.5),'taiwan':(121.,24.)}
STAGES={'surface_lights':dict(clouds=False,atmosphere=False,airglow=False),
        'plus_atmosphere':dict(clouds=False,atmosphere=True,airglow=False),
        'plus_airglow':dict(clouds=False,atmosphere=True,airglow=True),
        'complete':dict(clouds=True,atmosphere=True,airglow=True)}


def camera(lon,lat,radius=7971.,fov=28.):
    return dict(position=geographic(lon,lat,radius),target=geographic(lon,lat,6371.),up=np.array([0.,0.,1.]),fov=fov)


def panel(path,images,labels,width=960):
    canvas=Image.new('RGB',(width*len(images),round(width*9/16)+44),'#0b111c')
    draw=ImageDraw.Draw(canvas)
    for i,(a,title) in enumerate(zip(images,labels)):
        im=Image.fromarray(a);im.thumbnail((width,round(width*9/16)),Image.Resampling.LANCZOS)
        canvas.paste(im,(i*width,44));draw.text((i*width+8,8),title,fill='white')
    canvas.save(path)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--gain',type=float,default=1.);ap.add_argument('--name',default='renders')
    a=ap.parse_args();a.root=a.root.resolve()
    if Path(a.name).name!=a.name or not a.name.startswith('renders'):raise ValueError('Independent render directory name required')
    dest=a.root/a.name;dest.mkdir(exist_ok=False)
    cfg=load_config();day,_=load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',4096,
        'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night,nm=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',13500,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    water=np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    detail=np.load(a.root/'detail/east_asia_2016_500m.npy',mmap_mode='r',allow_pickle=False)
    dm=json.loads((a.root/'detail/east_asia_2016_500m.json').read_text())
    src,h,m,obs=expanded('1130');rgba=np.asarray(Image.open(src/'screened_candidate/B_current_material_rgba.png').convert('RGBA'))
    sun=sun_direction(utc_time(obs['nominal_utc']));metrics={};viewmeta={};gpus=[]
    options=dict(exposure=1.,city_light_gain=a.gain,volume_samples=96,height_scale=.4,thickness=.8)
    cameras={k:camera(*v) for k,v in VIEWS.items()}
    cameras['east_asia_oblique']=dict(position=geographic(109,25,10571),target=geographic(128.2,25,6371),up=np.array([0.,0.,1.]),fov=38)
    for size,selected in [(1920,cameras),(3840,{'japan_4k':camera(*VIEWS['japan'])})]:
        r=NativeCloudRenderer(day,night,size,size*9//16,1,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
        images={}
        try:
            r.update(rgba,h,m);gpus.append(r.device)
            for source in ['global3km','regional500m']:
                if source=='regional500m':r.set_night_detail(detail,dm['extent_wsen'])
                else:r.set_night_detail()
                for view,cam in selected.items():
                    viewmeta[view]={k:np.asarray(v).tolist() if k!='fov' else v for k,v in cam.items()}
                    for stage,settings in STAGES.items():
                        key=f'{view}_{source}_{stage}'
                        im=r.render(cam,sun,**options,**settings);images[key]=im
                        Image.fromarray(im).save(dest/(key+'.png'))
                        metrics[key]={'saturated_any_channel_fraction':float(np.any(im==255,axis=-1).mean())}
                    print('READY',view,source,size,r.device,flush=True)
                    # Mipmap is tested as a separate variable, not disabled in delivery.
                    tex=r.night_detail if source=='regional500m' else r.textures[1]
                    tex.filter=(moderngl.LINEAR,moderngl.LINEAR)
                    no_mip=r.render(cam,sun,**options,**STAGES['surface_lights'])
                    tex.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
                    base=images[f'{view}_{source}_surface_lights']
                    metrics[f'{view}_{source}_mip_off']=difference(base,no_mip)
                    if view=='east_asia_oblique':
                        tex.anisotropy=1
                        isotropic=r.render(cam,sun,**options,**STAGES['surface_lights']);tex.anisotropy=16
                        metrics[f'{view}_{source}_anisotropy1']=difference(base,isotropic)
                # Same source, same gain: a lights-OFF control isolates unrelated passes.
                if size==1920:
                    off=r.render(cameras['japan'],sun,**options,**STAGES['complete'],city_lights=False)
                    images[source+'_lights_off']=off
                    Image.fromarray(off).save(dest/(source+'_lights_off.png'))
            for view in selected:
                for stage in STAGES:
                    old=images[f'{view}_global3km_{stage}'];new=images[f'{view}_regional500m_{stage}']
                    panel(dest/f'{view}_{stage}_pair.jpg',[old,new],[f'2016 original 3km | gain{a.gain:g}, exposure1','2016 native 500m region | same settings'])
                    metrics[f'{view}_{stage}_source_difference']=difference(old,new)
                for source in ['global3km','regional500m']:
                    stages=[images[f'{view}_{source}_{s}'] for s in STAGES]
                    panel(dest/f'{view}_{source}_layers.jpg',stages,list(STAGES),width=640)
                    metrics[f'{view}_{source}_stage_effects']={
                        'atmosphere':difference(stages[0],stages[1]),'airglow':difference(stages[1],stages[2]),
                        'clouds':difference(stages[2],stages[3])}
                if view=='japan_4k':
                    for source in ['global3km','regional500m']:
                        crop=Image.fromarray(images[f'{view}_{source}_surface_lights']).crop((1400,650,2500,1500))
                        crop.save(dest/f'{source}_japan_4k_native_crop.png')
            if size==1920:
                assert np.array_equal(images['global3km_lights_off'],images['regional500m_lights_off'])
                metrics['complete_lights_off_exact']=True
                # Distinguish a preview's extra rescale from the original 3km source limit.
                with Image.open(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg') as im:
                    small=np.asarray(im.resize((4096,2048),Image.Resampling.LANCZOS)).copy()
                r.set_night_detail();tex=r.textures[1]
                # A separate renderer makes the intermediate-size change explicit.
                q=NativeCloudRenderer(day,small,1920,1080,1,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
                try:
                    q.update(rgba,h,m);gpus.append(q.device)
                    preview=q.render(cameras['japan'],sun,**options,**STAGES['surface_lights'])
                    Image.fromarray(preview).save(dest/'japan_4096_preview_surface_lights.png')
                    panel(dest/'preview_4096_vs_original13500.jpg',[preview,images['japan_global3km_surface_lights']],['Old preview resize4096',f'Original global13500 | same gain{a.gain:g}'])
                    metrics['preview_resize_difference']=difference(preview,images['japan_global3km_surface_lights'])
                finally:q.close()
        finally:r.close()
    assert len(set(gpus))==1,'Cross-GPU comparison invalid'
    report=dict(nominal_cloud_utc=obs['nominal_utc'],lights_reference_year=2016,cloud_material='existing screened_candidate, unchanged',
        options=options,stages=STAGES,cameras=viewmeta,gpus=gpus,source_global=nm,source_regional=dm,metrics=metrics,
        postprocessing='No bloom, sharpening, tone-map curve or contrast adjustment; same fixed exposure and sRGB conversion',
        grid_limit='500m product grid, not street-scale truth; global3km outside regional extent')
    verification='render_verification.json' if a.name=='renders' else a.name+'_verification.json'
    (a.root/verification).write_text(json.dumps(report,indent=2),encoding='utf-8')
    content='<meta charset="utf-8"><title>东亚夜光专项</title><style>body{background:#101722;color:#eee;font:16px sans-serif;margin:24px}img{max-width:100%}a{color:#9cf}</style><h1>夜间灯光专项：真实3km / 500m区域候选</h1><p>固定相机、曝光1、灯光gain1。2016静态灯光，真实2022-08-31 11:30 UTC轩岚诺云。未覆盖默认配置；未添加细节、锐化、bloom或对比度滤镜。</p>'
    content=content.replace('gain1。',f'gain{a.gain:g}。')
    content+='<p><a href="'+(ROOT/'docs/HINNAMNOR_NIGHT_LIGHTS_V1.md').as_uri()+'">中文审计与修复报告</a> | <a href="'+verification+'">参数、来源与逐层核验</a></p>'
    for p in sorted(dest.glob('*.jpg')):
        content+=f'<h2>{p.stem}</h2><a href="{a.name}/{p.name}"><img loading="lazy" src="{a.name}/{p.name}"></a>'
    content+='<h2>原始PNG与4K裁切</h2>'
    for p in sorted(dest.glob('*.png')):content+=f'<a href="{a.name}/{p.name}">{p.name}</a><br>'
    page='index.html' if a.name=='renders' else 'index_'+a.name+'.html'
    (a.root/page).write_text(content,encoding='utf-8')
    print('DELIVERED',len(list(dest.glob('*.png'))),'PNGs',flush=True)


if __name__=='__main__':main()
