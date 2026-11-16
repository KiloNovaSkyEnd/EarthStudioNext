"""Bounded native-pixel sampling for proxies and arbitrary camera-detail regions.

This initial Blender feasibility display is not the accepted L2 cloud-volume
renderer. Night blue remains an explicitly experimental spectral candidate;
SEVIRI daylight is a measured-monochrome/static-ground approximation.
"""
from contextlib import ExitStack
import json
from pathlib import Path
import numpy as np
from PIL import Image
import rasterio
from rasterio.windows import Window
from pyresample import create_area_def
from ges.geosampling import native_indices
from ges.catalog import utc_time
from ges.solar import solar_weights
from ges.day_atmosphere import geocolor_day_weight
from ges.blend import view_weight
from ges.blend_night import linear_rgb, encode_rgb
from ges.multispectral import night_layers
from .project import save, check_disk


def sample_window(dataset, area, longitude, latitude):
    ix, iy, valid = native_indices(area, longitude, latitude)
    out = np.full(valid.shape, np.nan, np.float32)
    if not valid.any():
        return out
    x0, x1 = int(ix[valid].min()), int(ix[valid].max())+1
    y0, y1 = int(iy[valid].min()), int(iy[valid].max())+1
    data = dataset.read(1, window=Window(x0, y0, x1-x0, y1-y0))
    out[valid] = data[iy[valid]-y0, ix[valid]-x0]
    return out


class NativeScene:
    def __init__(self, path, stack):
        path = Path(path)
        self.meta = json.loads(path.read_text(encoding='utf-8'))
        self.bands = {}
        for name, band in self.meta['bands'].items():
            h, w = band['shape']
            area = create_area_def(name, band['crs_wkt'], shape=(h,w), area_extent=band['extent'], units='m')
            self.bands[name] = (stack.enter_context(rasterio.open(path.parent/band['file'])), area)
        self.sensor = self.meta['sensor']
        lw, sw = ('B13','B07') if self.sensor=='himawari8' else ('C13','C07') if self.sensor.startswith('goes') else ('IR_108','IR_039')
        self.lw, self.sw = lw, sw
        p = self.bands[lw][1].proj_dict
        self.geometry = {'longitude': p['lon_0'], 'latitude': 0,
                         'earth_radius_m': p.get('a', 6378169), 'altitude_m': p['h']}
        timings = [self.meta['bands'][b] for b in (lw, sw)]
        self.start = min(utc_time(b['actual_start_utc']) for b in timings)
        self.end = max(utc_time(b['actual_end_utc']) for b in timings)
        if self.end < self.start:
            raise ValueError('Reversed native scan')

    def sample(self, name, lon, lat):
        dataset, area = self.bands[name]
        return sample_window(dataset, area, lon, lat)


class References:
    def __init__(self, day, night):
        self.day = np.asarray(Image.open(day).convert('RGB'))
        self.night = np.asarray(Image.open(night).convert('RGB'))

    @staticmethod
    def sample(image, lon, lat):
        lon, lat = np.broadcast_arrays(lon, lat)
        h, w = image.shape[:2]
        x = np.clip(((lon+180)/360*w).astype(int), 0, w-1)
        y = np.clip(((90-lat)/180*h).astype(int), 0, h-1)
        return image[y,x]


def pixels(sources, references, stamp, lon, lat):
    lon, lat = np.broadcast_arrays(lon, lat)
    elevation = solar_weights(stamp, lon, lat).elevation_deg
    day_factor = geocolor_day_weight(elevation)
    ground_day = References.sample(references.day, lon, lat)
    ground_night = np.maximum(References.sample(references.night, lon, lat), (3,4,10)).astype(np.uint8)
    fallback = linear_rgb(ground_day)*day_factor[...,None]+linear_rgb(ground_night)*(1-day_factor[...,None])
    numerator = np.zeros(lon.shape+(3,), np.float32)
    denominator = np.zeros(lon.shape, np.float32)
    count = np.zeros(lon.shape, np.uint8)
    dominant = np.zeros(lon.shape, np.uint8)
    best = np.zeros(lon.shape, np.float32)
    for index, source in enumerate(sources, 1):
        lw, sw = source.sample(source.lw, lon, lat), source.sample(source.sw, lon, lat)
        start = solar_weights(source.start, lon, lat).elevation_deg
        end = solar_weights(source.end, lon, lat).elevation_deg
        night, coverage, eligible, low, high = night_layers(lw, sw, lat, start, end)
        if source.sensor.startswith('meteosat'):
            # Preserve the established SEVIRI policy: no unsupported blue signal.
            low[:] = 0
            night, coverage, eligible, _, _ = night_layers(lw, np.full_like(sw,np.nan), lat, start, end)
        alpha = night[...,3].astype(np.float32)/255
        # Measured neutral longwave also bridges twilight where shortwave is solar-contaminated.
        cold = np.clip((285-np.where(coverage,lw,285))/105, 0, 1)
        bridge = np.repeat(cold[...,None],3,axis=-1)
        cloud_night = linear_rgb(night[...,:3])*alpha[...,None]+linear_rgb(ground_night)*(1-alpha[...,None])
        twilight = np.clip((elevation+6)/6, 0, 1)
        cloud_night = cloud_night*(1-twilight[...,None])+(
            bridge*cold[...,None]+linear_rgb(ground_night)*(1-cold[...,None]))*twilight[...,None]
        cosine = np.maximum(np.sin(np.deg2rad(elevation)), np.sin(np.deg2rad(6)))
        if source.sensor=='himawari8':
            red, green, blue = [source.sample(b, lon, lat)/100 for b in ('B03','B02','B01')]
            # Actual 500m red remains spatially independent of coarser green/blue.
            rgb = np.stack([red,green,blue],axis=-1)/cosine[...,None]
        elif source.sensor.startswith('goes'):
            blue, red, veggie = [source.sample(b, lon, lat)/100 for b in ('C01','C02','C03')]
            rgb = np.stack([red,.45*red+.10*veggie+.45*blue,blue],axis=-1)/cosine[...,None]
        else:
            vis = source.sample('VIS006', lon, lat)/100/cosine
            grey = np.clip(vis,0,1)
            a = 1-np.exp(-3*np.maximum(grey-.08,0))
            rgb = linear_rgb(ground_day)*(1-a[...,None])+grey[...,None]*a[...,None]
        valid_day = np.isfinite(rgb).all(axis=-1)&(start>0)&(end>0)
        display = np.clip((np.log10(np.clip(np.nan_to_num(rgb),.025,1.20))+1.6)/1.776,0,1)
        day_linear = linear_rgb(np.rint(display*255).astype(np.uint8))
        handoff = day_factor*valid_day
        combined = day_linear*handoff[...,None]+cloud_night*(1-handoff[...,None])
        weight = view_weight(lon,lat,source.geometry)*coverage
        numerator += combined*weight[...,None]
        denominator += weight
        count += coverage.astype(np.uint8)
        wins = weight > best
        dominant[wins] = index
        best[wins] = weight[wins]
    observed = denominator>0
    color = np.divide(numerator, denominator[...,None], out=fallback.copy(), where=observed[...,None])
    # Reference-only geography is distinct in the sidecar mask, never new cloud coverage.
    return encode_rgb(color), observed.astype(np.uint8)*255, dominant, count


def render_region(root, frame_index, bounds, width, height, label, references):
    root = Path(root)
    plan = json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    stamp = utc_time(plan['frames'][frame_index])
    destination = root/'processed'/'textures'/label
    destination.mkdir(parents=True,exist_ok=True)
    target = destination/f'frame_{frame_index+1:04d}.png'
    meta_path = target.with_suffix('.json')
    if meta_path.exists() and target.exists():
        old = json.loads(meta_path.read_text(encoding='utf-8'))
        if old['bounds_wsen']!=list(bounds) or old['shape']!=[height,width]:
            raise ValueError('Existing texture grid differs; choose a new label')
        return target
    descriptors = [s for s in plan['scenes'] if s['nominal_utc']==plan['frames'][frame_index]]
    check_disk(root,width*height*8)
    w,s,e,n = bounds
    color = np.empty((height,width,3),np.uint8)
    observed = np.empty((height,width),np.uint8)
    dominant = np.empty_like(observed)
    counts = np.empty_like(observed)
    with ExitStack() as stack:
        sources = [NativeScene(root/'processed'/'native'/d['scene_id']/'bands.json',stack) for d in descriptors]
        if not sources:
            raise ValueError('No observed sources available')
        # 128x256 chunks bound source read windows and projection working memory.
        chunk_y,chunk_x = (128,256) if width<=4096 else (512,512)
        for y in range(0,height,chunk_y):
            for x in range(0,width,chunk_x):
                ys,xs = slice(y,min(y+chunk_y,height)),slice(x,min(x+chunk_x,width))
                lon = w+(np.arange(xs.start,xs.stop)+.5)*(e-w)/width
                lat = n-(np.arange(ys.start,ys.stop)+.5)*(n-s)/height
                rgba,cov,dom,num = pixels(sources,references,stamp,lon[None,:],lat[:,None])
                color[ys,xs],observed[ys,xs],dominant[ys,xs],counts[ys,xs]=rgba,cov,dom,num
    Image.fromarray(color).save(target,compress_level=3)
    for suffix,values in [('coverage',observed),('source',dominant),('count',counts)]:
        Image.fromarray(values).save(destination/f'frame_{frame_index+1:04d}_{suffix}.png')
    meta = {'reference_utc':plan['frames'][frame_index], 'bounds_wsen':list(bounds), 'shape':[height,width],
        'sources':descriptors, 'observed_pixels':int((observed>0).sum()),
        'missing_sensor_count':5-len(descriptors),
        'reference_only_pixels':int((observed==0).sum()), 'is_proxy':label=='global_proxy',
        'recipe':'native-sampled-feasibility-display-v1',
        'day':'AHI measured RGB, ABI synthetic green; SEVIRI monochrome/static-reference approximation',
        'night':'measured IR; AHI/ABI blue is experimental spectral candidate, no L2 classification claim',
        'geometry':'surface composite, not retrieved volumetric clouds',
        'sampling':'single nearest-containing-native-pixel sampling per band; native caches retain original grids'}
    save(meta_path,meta)
    print('TEXTURE',label,frame_index+1,width,height,'observed',meta['observed_pixels'],flush=True)
    return target
