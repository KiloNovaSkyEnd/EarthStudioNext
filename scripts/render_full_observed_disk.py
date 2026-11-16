"""Full GOES-West visible disk from cached measured RGB and IR, no day map."""
import json
import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from pyresample.geometry import AreaDefinition
from scipy.ndimage import map_coordinates

from ges.atmosphere_scattering import geographic
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.observed_day import ObservedDayRenderer
from ges.observed_rgb import _sha
from ges.solar import sun_direction
from ges.storage import load_config


def sample(path, longitude, latitude, on_earth):
    """Containing cached geographic pixel; no nearest-valid borrowing."""
    data = np.asarray(Image.open(path))
    h,w = data.shape[:2]
    xy = [(90-np.where(on_earth,latitude,0))*h/180-.5,
          (np.where(on_earth,longitude,0)+180)*w/360-.5]
    if data.ndim == 2:
        result = map_coordinates(data,xy,order=0,mode='nearest')
    else:
        result = np.stack([map_coordinates(data[...,c],xy,order=0,mode='nearest') for c in range(data.shape[2])],-1)
    result[~on_earth] = 0
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--atmosphere-profile',choices=['legacy','limb-v2','limb-v3'],default='limb-v3',
                        help='limb-v3 uses the continuous horizon column; limb-v2 is a compatibility alias for the current renderer')
    parser.add_argument('--out',default='full_observed_disk_goes17_atmosphere_v3')
    args = parser.parse_args()
    cfg = load_config()
    out = cfg.processed_dir/args.out
    out.mkdir(exist_ok=False)
    daypath = cfg.processed_dir/'day_night_v8/daylight_west/goes_daylight.png'
    irpath = cfg.processed_dir/'day_night_v6/west_transition/goes17_transition_ir.png'
    daymeta = json.loads(daypath.with_suffix('.json').read_text())
    irmeta = json.loads(irpath.with_suffix('.json').read_text())
    assert daymeta['satellite'] == irmeta['satellite'] == 'goes17'
    assert daymeta['scan_start_utc'] == irmeta['scan_start_utc']
    assert daymeta['scan_end_utc'] == irmeta['scan_end_utc']
    stamp = daymeta['observed_utc']
    rawmeta = json.loads(Path(daymeta['source_manifest']).read_text())
    raw = Path(rawmeta['local_files'][0])
    assert raw.stat().st_size == rawmeta['object_sizes'][0]
    # This is an explicitly declared display reprojection of ABI sweep-x data
    # already mapped to EPSG:4326. Do not pretend ABI's native grid is sweep-y.
    projection = dict(proj='geos',lon_0=-137.,h=35786023.,a=6378137.,b=6356752.31414,sweep='y')
    extent = [-5500000.,-5500000.,5500000.,5500000.]
    n = 2400
    area = AreaDefinition('virtual_display','virtual display sweep-y','geos',projection,n,n,extent)
    lon,lat = area.get_lonlats()
    on_earth = np.isfinite(lon)&np.isfinite(lat)
    day = sample(daypath,lon,lat,on_earth)
    cloud = sample(irpath,lon,lat,on_earth)
    valid = on_earth&(day[...,3] == 255)
    Image.fromarray(valid.astype('uint8')*255).save(out/'rgb_support.png')
    print('SOURCE_READY',stamp,int(valid.sum()),flush=True)
    night,_ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',8192,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    nav = dict(projection=projection,extent_m=extent,nominal_utc=stamp)
    obs = dict(projection=projection,area_extent_m=extent,nominal_utc=stamp,output_shape_yx=[n,n],source_fade_applied=False)
    cam = dict(position=geographic(-137.,0.,40000.),target=np.zeros(3),up=np.array([0.,0.,1.]),fov=21.)
    from ges.observed_atmosphere import ObservedAtmosphereRenderer
    renderer = ObservedAtmosphereRenderer if args.atmosphere_profile != 'legacy' else ObservedDayRenderer
    r = renderer(night,1800,1800,2. if args.atmosphere_profile != 'legacy' else 1.,ocean_mask=water)
    try:
        r.update(cloud,np.full((n//2,n//2),np.nan,np.float32),nav)
        r.set_observation(day[...,:3].astype(np.float32)/255,valid,obs)
        if isinstance(r,ObservedAtmosphereRenderer):
            ir_coverage=sample(irpath.with_name('goes17_transition_ir_coverage.png'),lon,lat,on_earth)>0
            r.set_ir_support(ir_coverage,obs)
        image = r.render(cam,sun_direction(utc_time(stamp)),exposure=1.,city_light_gain=.75,
                         height_scale=.4,thickness=.8,volume_samples=64)
        Image.fromarray(image).save(out/'earth_disk.png')
        coverage = r.render(cam,sun_direction(utc_time(stamp)),coverage_debug=True,
                            exposure=1.,city_light_gain=.75,volume_samples=64)
        Image.fromarray(coverage).save(out/'coverage.png')
        gpu = r.device
    finally:
        r.close()
    with Image.open(out/'earth_disk.png') as image:
        image.load()
        assert image.size == (1800,1800)
    sources = [daypath,daypath.with_suffix('.json'),irpath,irpath.with_suffix('.json'),raw,
               irpath.with_name('goes17_transition_ir_coverage.png')]
    record = dict(observed_utc=stamp,scan_start_utc=daymeta['scan_start_utc'],scan_end_utc=daymeta['scan_end_utc'],
        satellite='GOES-17',size=[1800,1800],gpu=gpu,download_bytes=0,atmosphere_profile=args.atmosphere_profile,
        inputs_sha256={str(p):_sha(p) for p in sources},
        daylight='Existing actual ABI C01/C02/C03 apparent RGB including land/ocean/clouds; CIMSS estimated green, Rayleigh/log display; no static daytime map.',
        night='Same-scan measured IR/L2 cloud display and static BlackMarble2016 city-light reference; IR tint/opacity and atmosphere/Airglow are display models.',
        geometry='Native ABI sweep-x -> existing geographic cache -> declared sweep-y display grid. Reprojected displayed data, not new native measurements.',
        cloud_height='No delivered height loaded for this preview; unknown-height display shell, no invented cloud height.',
        scope='One complete visible hemisphere from GOES-West, not simultaneous observations of the far side or polar coverage.',
        source_rgb_metadata=daymeta,source_ir_metadata=irmeta)
    (out/'metadata.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>完整地球圆盘</title>'
        '<style>body{background:#05080d;color:#ddd;font:17px sans-serif}img{max-width:100%;width:1800px}</style>'
        '<h1>完整地球圆盘：太平洋晨昏</h1><p>GOES-17，2020-10-29 16:40:32 UTC开始的整圆盘扫描。'
        '日侧陆地/海洋/云来自实际RGB；夜侧为实测IR云与2016夜光参考。不是2022东亚时次或地球背面的同步观测。'
        '无固定日间海陆底图，无新增下载。</p><img src="earth_disk.png"><p><a href="metadata.json">来源和处理说明</a> · '
        '<a href="coverage.png">观测覆盖诊断</a></p>',encoding='utf-8')
    print(out/'earth_disk.png',flush=True)


if __name__ == '__main__':
    main()
