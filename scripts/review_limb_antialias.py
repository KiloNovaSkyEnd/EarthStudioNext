"""Controlled silhouette AA review, fixed real source and solar geometry."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

from ges.atmosphere_scattering import geographic,camera_basis,sphere_roots
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.observed_atmosphere import ObservedAtmosphereRenderer
from ges.observed_rgb import _sha
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.review_hinnamnor_ocean import frame
from scripts.review_observed_day import panel
from scripts.review_observed_twilight import load_source


def main():
    cfg=load_config()
    out=cfg.processed_dir/'observed_limb_antialias_v1'
    out.mkdir(exist_ok=False)
    rgb,obs=load_source(cfg.processed_dir/'observed_twilight_sampling_v2','0830')
    rgba,heights,nav,_,src=frame('0830',True)
    nav['nominal_utc']=obs['nominal_utc']
    with np.load(src/'official_layers.npz') as data:
        kelvin=data['B13_1km']
        ir_support=np.isfinite(kelvin)&(kelvin>=100)&(kelvin<=350)
    night,_=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',8192,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    water=np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    position=geographic(117.,21.,7171.)
    cam=dict(position=position,target=geographic(128.2,25.,6371.),up=position/np.linalg.norm(position),fov=26.)
    sun=sun_direction(utc_time(obs['nominal_utc']))
    settings=dict(exposure=1.,city_light_gain=.75,height_scale=.4,thickness=.8,volume_samples=64)
    results={}
    records=dict(utc=obs['nominal_utc'],settings=settings,variants={},
        scope='Same source colours, atmospheric density/solar model, Airglow and camera. Sampling/resolve only; no source blur or texture generation.')
    for name,ss,aa,linear in [('before_1x',1.,False,False),('after_1x',1.,True,True),
                             ('before_2x',2.,False,False),('after_2x',2.,True,True),('reference_4x',4.,False,True)]:
        r=ObservedAtmosphereRenderer(night,1600,900,ss,ocean_mask=water,limb_antialias=aa,linear_resolve=linear)
        try:
            r.update(rgba,heights,nav)
            r.set_observation(rgb,np.isfinite(rgb).all(-1),obs)
            r.set_ir_support(ir_support,obs)
            image=r.render(cam,sun,**settings)
            Image.fromarray(image).save(out/(name+'.png'))
            results[name]=image
            records['variants'][name]=dict(supersample=ss,limb_subrays=16 if aa else 1,linear_resolve=linear,gpu=r.device)
            print('READY',name,flush=True)
        finally:
            r.close()
    for ss in ['1x','2x']:
        panel(out/('pair_'+ss+'.png'),[results['before_'+ss],results['after_'+ss]],['BEFORE '+ss,'AFTER '+ss+' | local ray coverage, no image blur'])
    for name,box in [('left',(0,145,280,245)),('right',(1150,75,1500,185)),('center',(600,80,1000,180))]:
        pieces=[]
        for version in ['before_1x','after_1x','after_2x']:
            pieces.append(np.asarray(Image.fromarray(results[version]).crop(box).resize(((box[2]-box[0])*3,(box[3]-box[1])*3),Image.Resampling.NEAREST)))
        panel(out/(name+'_detail.png'),pieces,['BEFORE 1x','AFTER 1x','AFTER 2x'])
    right,up,forward=camera_basis(position,cam['target'],cam['up'])
    yy,xx=np.indices((900,1600))
    ray=forward+np.tan(np.deg2rad(13))*((2*(xx+.5)-1600)[...,None]/900*right+(900-2*(yy+.5))[...,None]/900*up)
    ray/=np.linalg.norm(ray,axis=-1,keepdims=True)
    tangent_height=np.linalg.norm(np.cross(position,ray),axis=-1)-6371
    edge=abs(tangent_height)<12
    reference=results['reference_4x'].astype(float)
    for name,image in results.items():
        delta=image.astype(float)-reference
        records['variants'][name]['limb_mae_dn_against_4x']=float(abs(delta[edge]).mean())
        records['variants'][name]['limb_rmse_dn_against_4x']=float(np.sqrt((delta[edge]**2).mean()))
    records['metric_note']='±12km analytic tangent band;4x discrete reference is finite-sample evidence, not observed truth or converged radiometric accuracy.'
    records['inputs_sha256']={str(p):_sha(p) for p in [cfg.processed_dir/'observed_twilight_sampling_v2/sources/0830/rgb.npy',
        cfg.processed_dir/'observed_twilight_sampling_v2/sources/0830/metadata.json',src/'official_layers.npz']}
    for path in out.glob('*.png'):
        with Image.open(path) as im: im.load()
    (out/'verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>轮廓抗锯齿</title>'
        '<style>body{background:#080d15;color:#ddd;font:17px sans-serif;margin:24px}img{max-width:100%}a{color:#8cf}</style>'
        '<h1>球体与大气轮廓：局部射线抗锯齿</h1><p>同一2022-08-31 08:30 UTC卫星源、相机、太阳与大气。'
        '只对轮廓附近计算像素内16条射线，在线性光中合成；高分辨率缩图改为面积解析，避免暗边振铃。'
        '不模糊整张云海影像，不改晨昏紫色或气辉。原profile_only是1x算法诊断，不是最终抗锯齿图。</p>'
        '<h2>最终图</h2><a href="after_2x.png"><img src="after_2x.png"></a>'
        +''.join(f'<h2>{n}箭头附近放大：旧1x / 新1x / 新2x</h2><img src="{n}_detail.png">' for n in ['left','right','center'])
        +'<h2>相同2x采样前后</h2><img src="pair_2x.png"><p><a href="verification.json">参数与验证</a></p>',encoding='utf-8')


if __name__=='__main__':
    main()
