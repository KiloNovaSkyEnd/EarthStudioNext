"""Fixed-source atmosphere/airglow ablations and real oblique-camera review."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from pyresample.geometry import AreaDefinition

from ges.atmosphere_scattering import geographic, orbit_camera
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.observed_day import ObservedDayRenderer
from ges.observed_atmosphere import ObservedAtmosphereRenderer
from ges.observed_rgb import _sha
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.render_full_observed_disk import sample
from scripts.review_observed_day import panel
from scripts.review_observed_twilight import load_source
from scripts.review_hinnamnor_ocean import frame, camera
from scripts.audit_render_baseline import difference


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--out',default='observed_atmosphere_review_v1')
    parser.add_argument('--before-dir',help='Prior immutable review, compare its after.png with the new result')
    parser.add_argument('--typhoon-only',action='store_true')
    args = parser.parse_args()
    cfg = load_config()
    out = cfg.processed_dir/args.out
    out.mkdir(exist_ok=False)
    source = cfg.processed_dir/'full_observed_disk_goes17_v1/metadata.json'
    source_record = json.loads(source.read_text())
    daypath = cfg.processed_dir/'day_night_v8/daylight_west/goes_daylight.png'
    irpath = cfg.processed_dir/'day_night_v6/west_transition/goes17_transition_ir.png'
    paths = [daypath,irpath,daypath.with_suffix('.json'),irpath.with_suffix('.json')]
    protected = {str(p):_sha(p) for p in paths}
    projection = dict(proj='geos',lon_0=-137.,h=35786023.,a=6378137.,b=6356752.31414,sweep='y')
    extent = [-5500000.,-5500000.,5500000.,5500000.]
    n = 2400
    area = AreaDefinition('display','display','geos',projection,n,n,extent)
    lon,lat = area.get_lonlats()
    on_earth = np.isfinite(lon)&np.isfinite(lat)
    day = sample(daypath,lon,lat,on_earth)
    rgba = sample(irpath,lon,lat,on_earth)
    ircoverage=cfg.processed_dir/'day_night_v6/west_transition/goes17_transition_ir_coverage.png'
    ir_support=sample(ircoverage,lon,lat,on_earth)>0
    protected[str(ircoverage)]=_sha(ircoverage)
    rgb = day[...,:3].astype('float32')/255
    valid = on_earth&(day[...,3] == 255)
    stamp = source_record['observed_utc']
    nav = dict(projection=projection,extent_m=extent,nominal_utc=stamp)
    obs = dict(projection=projection,area_extent_m=extent,nominal_utc=stamp,output_shape_yx=[n,n],source_fade_applied=False)
    night,_ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',8192,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    disk = dict(position=geographic(-137.,0.,40000.),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=21.)
    settings = dict(exposure=1.,city_light_gain=.75,height_scale=.4,thickness=.8,volume_samples=64)
    records = dict(inputs_sha256=protected,cases={},settings=settings,profile='continuous-tangent-column-v3',
        limits='Enhanced apparent RGB, approximate additional camera path, not calibrated atmospheric inversion. Oblique views reproject source clouds, not free-view cloud geometry.')

    def render_case(name,cam,rgb,valid,rgba,heights,nav,obs,width,height,ir_support):
        images = []
        record = dict(utc=obs['nominal_utc'],views={})
        for label,cls,ss in [('before',ObservedDayRenderer,1.),('profile_only',ObservedAtmosphereRenderer,1.),('after',ObservedAtmosphereRenderer,2.)]:
            if label=='before' and args.before_dir:
                path=cfg.processed_dir/args.before_dir/(name+'_after.png')
                image=np.asarray(Image.open(path).convert('RGB'))
                assert image.shape==(height,width,3)
                Image.fromarray(image).save(out/(name+'_before.png'))
                images.append(image)
                record['views'][label]=dict(immutable_input=str(path),sha256=_sha(path),supersample=2.)
                continue
            r = cls(night,width,height,ss,ocean_mask=water)
            try:
                r.update(rgba,heights,nav)
                r.set_observation(rgb,valid,obs)
                if isinstance(r,ObservedAtmosphereRenderer):
                    r.set_ir_support(ir_support,obs)
                sun = sun_direction(utc_time(obs['nominal_utc']))
                image = r.render(cam,sun,**settings)
                Image.fromarray(image).save(out/(name+'_'+label+'.png'))
                if label != 'profile_only':
                    images.append(image)
                record['views'][label] = dict(gpu=r.device,supersample=ss)
                if label == 'after':
                    for part,options in [('no_airglow',dict(airglow=False)),('no_atmosphere',dict(atmosphere=False,airglow=False))]:
                        diagnostic = r.render(cam,sun,**settings,**options)
                        Image.fromarray(diagnostic).save(out/(name+'_'+part+'.png'))
                        record[part+'_delta'] = difference(image,diagnostic)
            finally:
                r.close()
        panel(out/(name+'_pair.png'),images,['BEFORE','AFTER | camera-path atmosphere + 2x supersampling'])
        records['cases'][name] = record
        print('CASE_READY',name,record,flush=True)

    if not args.typhoon_only:
        render_case('disk',disk,rgb,valid,rgba,np.full((1200,1200),np.nan,'float32'),nav,obs,1600,1600,ir_support)
        render_case('day_oblique',orbit_camera(-150.,12.,700.,45.,heading=1),rgb,valid,rgba,
            np.full((1200,1200),np.nan,'float32'),nav,obs,1600,900,ir_support)
    rgba,h,nav,meta,_ = frame('0830',True)
    rgb,obs = load_source(cfg.processed_dir/'observed_twilight_sampling_v2','0830')
    nav['nominal_utc'] = obs['nominal_utc']
    ir_input=cfg.processed_dir/'hinnamnor_geocolor_v1/0830/official_layers.npz'
    with np.load(ir_input) as data:
        kelvin=data['B13_1km']
        ir_support=np.isfinite(kelvin)&(kelvin>=100)&(kelvin<=350)
    protected[str(ir_input)]=_sha(ir_input)
    position=geographic(117.,21.,7171.)
    typhoon_camera=dict(position=position,target=geographic(128.2,25.,6371.),up=position/np.linalg.norm(position),fov=26.)
    render_case('typhoon_oblique',typhoon_camera,rgb,np.isfinite(rgb).all(-1),rgba,h,nav,obs,1600,900,ir_support)
    assert all(_sha(Path(p)) == digest for p,digest in protected.items())
    decoded = 0
    for path in out.glob('*.png'):
        with Image.open(path) as im:
            im.load()
        decoded += 1
    records['fully_decoded_pngs'] = decoded
    (out/'verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>大气厚度与斜视验证</title>'
        '<style>body{background:#080d15;color:#ddd;font:17px sans-serif;margin:24px}img{max-width:100%}a{color:#8cf}</style>'
        '<h1>连续大气：圆盘 / 白天斜视 / 台风斜视</h1><p>每组左旧 / 右新。只读同一源图；新图2倍线性尺寸超采样。'
        '移除地平线内侧高度截断，高空雾光独立于地面VIS淡出；暮光IR仅作中性雾化。'
        '天顶天空近似补偿为展示模型，不是完整多次散射或实测大气反演。'
        'GOES-17：2020-10-29 16:40 UTC；台风Hinnamnor：2022-08-31 08:30 UTC。'
        '台风斜视仍为观测影像重投影，不是新增自由视角三维云。缺测不填画。</p>'
        +''.join(f'<h2>{name}</h2><a href="{name}_after.png"><img src="{name}_pair.png"></a>'
            f'<p><a href="{name}_profile_only.png">仅算法变化，1x采样</a> · '
            f'<a href="{name}_no_airglow.png">气辉关闭</a> · <a href="{name}_no_atmosphere.png">大气与气辉关闭</a></p>' for name in records['cases'])
        +'<a href="verification.json">验证与来源</a>',encoding='utf-8')


if __name__ == '__main__':
    main()
