"""One cached observed-mode disk, explicit uncovered daytime pixels."""
import json

import numpy as np
from PIL import Image

from ges.atmosphere_scattering import geographic
from ges.catalog import utc_time
from ges.film_transition import load_reference
from ges.observed_day import ObservedDayRenderer
from ges.solar import sun_direction
from ges.storage import load_config
from scripts.review_hinnamnor_ocean import frame
from scripts.review_observed_twilight import load_source


def main():
    cfg = load_config()
    out = cfg.processed_dir/'observed_twilight_sampling_v2/disk_1000_v1'
    out.mkdir(exist_ok=False)
    rgb, obs = load_source(cfg.processed_dir/'observed_twilight_sampling_v2', '1000')
    rgba, heights, nav, _, _ = frame('1000', True)
    nav['nominal_utc'] = obs['nominal_utc']
    night, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg', 13500,
        'static reference night-lights composite, not contemporaneous with satellite clouds')
    detail = cfg.processed_dir/'hinnamnor_lights_v1/detail'
    lm = json.loads((detail/'east_asia_2016_500m.json').read_text())
    water = np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    cam = dict(position=geographic(115., 15., 24000.), target=np.zeros(3),
               up=np.array([0., 0., 1.]), fov=36.)
    renderer = ObservedDayRenderer(night, 1536, 1536, 1, opacity_gamma=1.25,
                                 geometry_bridge_pixels=2, ocean_mask=water)
    try:
        renderer.set_night_detail(np.load(detail/'east_asia_2016_500m.npy', mmap_mode='r'), lm['extent_wsen'])
        renderer.update(rgba, heights, nav)
        renderer.set_observation(rgb, np.isfinite(rgb).all(-1), obs)
        image = renderer.render(cam, sun_direction(utc_time(obs['nominal_utc'])), exposure=1.,
            city_light_gain=.75, height_scale=.4, thickness=.8, volume_samples=64)
        Image.fromarray(image).save(out/'disk.png')
        with Image.open(out/'disk.png') as check:
            check.load()
            assert check.size == (1536, 1536)
        record = dict(nominal_utc=obs['nominal_utc'], resolution=[1536,1536], gpu=renderer.device,
            camera={k: v.tolist() if isinstance(v,np.ndarray) else v for k,v in cam.items()},
            profile=obs['photometry_profile'],
            scope='Regional AHI observations on a full sphere; hatched daytime is missing observation, not ocean. No global observed-data coverage claim.',
            verification='Rendered and PNG fully decoded; no renderer/source modifications or downloads.')
        (out/'metadata.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    finally:
        renderer.close()
    with (cfg.processed_dir.parents[1]/'docs/PROGRESS.md').open('a',encoding='utf-8') as stream:
        stream.write('\n### 2026-10-20 快速圆盘图\n\n复用v2修复源与既有IR/云/夜光，输出1536×1536完整圆盘，真实2022-08-31 10:00 UTC昼夜交界。相机115°E/15°N、距地心24000km；大气/Airglow保持。源仅东亚，日侧缺测仍明确标纹，不冒充完整全球观测。未下载或改渲染器；PNG尺寸和完整解码检查通过。文件：data/processed/observed_twilight_sampling_v2/disk_1000_v1/disk.png，参数与限制见同目录metadata.json。\n')
    print(out/'disk.png', flush=True)


if __name__ == '__main__':
    main()
