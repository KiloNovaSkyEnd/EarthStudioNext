"""Experimental night spectral enhancement, NOT a categorical cloud retrieval.

Inspired by Miller et al. (2020), GeoColor nightside, section 5:
https://doi.org/10.1175/JTECH-D-19-0134.1
This is not the operational GeoColor algorithm. No land/sea mask or DEBRA;
use the stricter land BTD range everywhere and expose that limitation.
"""
import json
from pathlib import Path
import warnings

import numpy as np
from PIL import Image

from .catalog import utc_time
from .download import read_manifest
from .render import create_satpy_scene, make_global_area, mask_goes_ir_quality, observation_interval
from .solar import solar_weights


def night_layers(longwave, shortwave, latitude, elevation_start, elevation_end):
    """Return straight-alpha display + longwave coverage + night eligibility.

    Blue is a liquid-cloud spectral candidate, not measured height or fog.
    White is a cold-IR enhancement, never a convection classification.
    Day/twilight (at either scan endpoint) cannot activate the blue signal.
    """
    lw, sw, lat, start, end = np.broadcast_arrays(*[
        np.asarray(v, dtype=np.float32) for v in
        (longwave, shortwave, latitude, elevation_start, elevation_end)])
    coverage = np.isfinite(lw) & (lw >= 100) & (lw <= 350)
    paired = coverage & np.isfinite(sw) & (sw >= 100) & (sw <= 350)
    geometry = np.isfinite(lat) & (np.abs(lat) <= 90) & np.isfinite(start) & np.isfinite(end)
    night = coverage & geometry & (start <= -6) & (end <= -6)
    safe_lw = np.where(coverage, lw, 280)
    safe_sw = np.where(paired, sw, 280)
    cold = 200 + 20 * np.clip((np.abs(lat)-30)/30, 0, 1)
    high = np.where(night, np.clip((280-safe_lw)/(280-cold), 0, 1), 0)
    low = np.where(night & paired & (safe_lw >= 230), np.clip((safe_lw-safe_sw-1)/3.5, 0, 1), 0)
    alpha = high + (1-high)*low
    premult = high[..., None] + ((1-high)*low)[..., None]*np.array([.55,.75,.98], dtype=np.float32)
    rgb = np.divide(premult, alpha[..., None], out=np.zeros_like(premult), where=alpha[..., None] > 0)
    rgba = np.concatenate([rgb, alpha[..., None]], axis=-1)
    return np.rint(np.clip(rgba, 0, 1)*255).astype(np.uint8), coverage, night, low, high


def calibrated_pair(meta):
    satellite = meta['satellite']
    if satellite.startswith('himawari'):
        bands = ('B13','B07')
    elif satellite.startswith('goes'):
        bands = ('C13','C07')
    elif satellite.startswith('meteosat_'):
        bands = ('IR_108','IR_039')
    else:
        raise ValueError('Only verified AHI/ABI/SEVIRI band mappings are supported')
    scene = create_satpy_scene(meta['local_files'], satellite)
    scene.load(list(bands))
    policies = []
    for band, expected_um in zip(bands, (10.8 if satellite.startswith('meteosat_') else 10.4,3.9)):
        attrs = scene[band].attrs
        if str(attrs.get('units','')).lower() not in ('k','kelvin'):
            raise ValueError('Both source bands must be calibrated Kelvin brightness temperatures')
        wavelength = attrs['wavelength'].central
        if abs(wavelength-expected_um) > .15:
            raise ValueError('Unexpected IR band wavelength')
        if satellite.startswith('goes'):
            policies.append(mask_goes_ir_quality(scene,meta['local_files'],band))
        elif satellite.startswith('himawari'):
            policies.append('Satpy HSD invalid/calibration mask; finite 100..350 K')
        else:
            policies.append('Satpy native count-zero mask and nominal calibration; finite 100..350 K; no extra scanline flag filter')
    first, second = (scene[band] for band in bands)
    if first.attrs['area'] != second.attrs['area'] or first.shape != second.shape:
        raise ValueError('IR source band grids differ')
    intervals=[observation_interval(scene[band].attrs) for band in bands]
    starts,ends=zip(*intervals)
    if None in starts+ends:raise ValueError('IR bands require verified observation intervals')
    if starts[0]!=starts[1] or ends[0]!=ends[1]:
        # AHI detector offsets give B07/B13 slightly different actual windows
        # in the same nominal scan (0.627 s in the verified 2020 scene).
        nominal=[(scene[b].attrs.get('start_time'),scene[b].attrs.get('end_time')) for b in bands]
        if (not satellite.startswith('himawari') or nominal[0]!=nominal[1]
                or abs((utc_time(starts[0])-utc_time(starts[1])).total_seconds())>1
                or abs((utc_time(ends[0])-utc_time(ends[1])).total_seconds())>1):
            raise ValueError('IR bands differ in nominal scan or exceed verified one-second AHI detector timing guard')
        for i in range(2):policies[i]+=f'; actual band interval {starts[i]}..{ends[i]}'
    if utc_time(ends[0]) < utc_time(starts[0]):
        raise ValueError('Reversed scan interval')
    return scene, bands, min(starts), max(ends), policies


def sensor_display_policy(rgba,low,high,satellite):
    """SEVIRI BTD thresholds are unvalidated: retain measured cold IR only."""
    if satellite.startswith('meteosat_'):
        rgba=rgba.copy(); low=np.zeros_like(low)
        rgba[...,:3]=255
        rgba[...,3]=np.rint(high*255).astype(np.uint8)
    return rgba,low


def render_multispectral(manifests, lights, out_dir, width=2048, base=None):
    """Ordered measured longwave coverage overlay, keeping band availability."""
    area = make_global_area(width)
    manifests = [Path(p) for p in manifests]
    if not manifests or len(manifests) > 255:
        raise ValueError('Provide 1..255 actual scene manifests')
    metas = [read_manifest(p) for p in manifests]
    out_dir, lights = Path(out_dir), Path(lights)
    if any(p.parent.resolve() == out_dir.resolve() or p.parent.resolve() in out_dir.resolve().parents for p in manifests):
        raise ValueError('Processed output must be outside raw scene directories')
    reference = json.loads(lights.with_suffix('.json').read_text(encoding='utf-8'))
    if (reference.get('projection') != 'EPSG:4326' or reference.get('extent_wsen') != [-180,-90,180,90]
            or reference.get('kind') != 'static reference night-lights composite, not contemporaneous with satellite clouds'):
        raise ValueError('A documented static global night-lights reference is required')
    shape = (width//2,width)
    canvas = np.zeros(shape+(4,),dtype=np.uint8)
    source_index = np.zeros(shape,dtype=np.uint8)
    night_mask = np.zeros(shape,dtype=np.uint8)
    low_signal = np.zeros(shape,dtype=np.uint8)
    high_signal = np.zeros(shape,dtype=np.uint8)
    paired_mask = np.zeros(shape,dtype=np.uint8)
    sources = []
    base_meta=None
    if base is not None:
        base=Path(base)
        base_meta=json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
        if (base_meta.get('display_recipe')!='night-multispectral-experimental-v1'
                or base_meta.get('projection')!='EPSG:4326'
                or base_meta.get('extent_wsen')!=[-180,-90,180,90]
                or (base_meta.get('height'),base_meta.get('width'))!=shape
                or base.parent.resolve()==out_dir.resolve()):
            raise ValueError('Base must be a matching multispectral grid in another output directory')
        def read_layer(name, mode):
            path=base if name is None else base.parent/(base.stem+'_'+name+'.png')
            with Image.open(path) as im:
                if im.mode!=mode or im.size!=(width,width//2):
                    raise ValueError('Base layer dimensions/mode differ')
                return np.asarray(im).copy()
        canvas=read_layer(None,'RGBA')
        source_index=read_layer('source_index','L')
        night_mask=read_layer('night_eligible','L')
        low_signal=read_layer('low_spectral_signal','L')
        high_signal=read_layer('cold_ir_signal','L')
        paired_mask=read_layer('paired_band_coverage','L')
        sources=list(base_meta['sources'])
        if (len(sources)+len(metas)>255 or source_index.max()>len(sources)
                or not np.isin(night_mask,[0,255]).all() or not np.isin(paired_mask,[0,255]).all()
                or (canvas[source_index==0,3]>0).any()
                or (canvas[night_mask==0,3]>0).any() or (low_signal[paired_mask==0]>0).any()):
            raise ValueError('Invalid base masks or source indices')
    lon = -180+(np.arange(width)+.5)*360/width
    for index, (path, meta) in enumerate(zip(manifests,metas),len(sources)+1):
        scene,bands,start,end,policies = calibrated_pair(meta)
        mapped = scene.resample(area,resampler='nearest',reduce_data=False)
        lw,sw = [np.ma.filled(mapped[band].compute().values,np.nan) for band in bands]
        contributed = observed = paired_count = 0
        for row in range(0,shape[0],128):
            sl = slice(row,min(row+128,shape[0]))
            lat = 90-(np.arange(sl.start,sl.stop)+.5)*360/width
            elev_start = solar_weights(utc_time(start),lon[None,:],lat[:,None]).elevation_deg
            elev_end = solar_weights(utc_time(end),lon[None,:],lat[:,None]).elevation_deg
            rgba,coverage,night,low,high = night_layers(lw[sl],sw[sl],lat[:,None],elev_start,elev_end)
            rgba,low=sensor_display_policy(rgba,low,high,meta.get('satellite',''))
            new = coverage & (source_index[sl] == 0)
            canvas[sl][new] = rgba[new]
            source_index[sl][new] = index
            night_mask[sl][new] = night[new].astype(np.uint8)*255
            low_signal[sl][new] = np.rint(low[new]*255).astype(np.uint8)
            high_signal[sl][new] = np.rint(high[new]*255).astype(np.uint8)
            paired = coverage & np.isfinite(sw[sl]) & (sw[sl]>=100) & (sw[sl]<=350)
            paired_mask[sl][new] = paired[new].astype(np.uint8)*255
            paired_count += int(paired.sum())
            observed += int(coverage.sum()); contributed += int(new.sum())
        sources.append({'manifest':str(path.resolve()),'source_provenance':meta,'bands':bands,
                        'blue_enhancement_enabled':not meta.get('satellite','').startswith('meteosat_'),
                        'scan_start_utc':start,'scan_end_utc':end,'quality_policy':policies,
                        'observed_longwave_pixels':observed,'observed_common_band_pixels':paired_count,
                        'contributed_pixels':contributed})
        del scene,mapped,lw,sw
    coverage = source_index != 0
    stamp = base_meta['reference_utc'] if base_meta else metas[0]['observed_utc']
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',Image.DecompressionBombWarning)
        with Image.open(lights) as image:
            if image.size != (reference['width'],reference['height']) or image.width != image.height*2:
                raise ValueError('Static-reference image differs from its provenance')
            surface = np.asarray(image.convert('RGB').resize((width,width//2),Image.Resampling.LANCZOS)).copy()
    for row in range(0,shape[0],128):
        sl=slice(row,min(row+128,shape[0])); lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
        weight=solar_weights(utc_time(stamp),lon[None,:],lat[:,None]).city_lights
        surface[sl]=np.maximum(np.rint(surface[sl]*weight[...,None]).astype(np.uint8),(4,5,12))
    surface[~coverage]=(24,11,35)
    out_dir.mkdir(parents=True,exist_ok=True)
    target=out_dir/'night_multispectral.png'
    surface_path=out_dir/'night_multispectral_surface.png'
    Image.fromarray(canvas).save(target)
    Image.fromarray(surface).save(surface_path)
    for name, data in [('coverage',coverage.astype(np.uint8)*255),('source_index',source_index),
                       ('paired_band_coverage',paired_mask),
                       ('night_eligible',night_mask),('low_spectral_signal',low_signal),('cold_ir_signal',high_signal)]:
        Image.fromarray(data).save(out_dir/f'night_multispectral_{name}.png')
    preview = surface.astype(np.float32)
    alpha = canvas[...,3:4].astype(np.float32)/255
    preview = np.rint(canvas[...,:3]*alpha+preview*(1-alpha)).astype(np.uint8)
    Image.fromarray(preview).save(out_dir/'night_multispectral_preview.png')
    metadata={'product':'ir-night-display','display_recipe':'night-multispectral-experimental-v1',
              'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':width,'height':width//2,
              'reference_utc':stamp,'observed_utc':stamp,'sources':sources,
              'source_ir_coverage':'night_multispectral_coverage.png','night_surface':surface_path.name,
              'observed_pixels':int(coverage.sum()),'missing_pixels':int((~coverage).sum()),
              'paired_band_pixels':int((paired_mask>0).sum()),
              'shortwave_missing_policy':'Retain valid measured longwave high-IR signal; disable blue signal. No inferred shortwave values.',
              'is_cloud_mask':False,'is_opacity_retrieval':False,'is_convection_classification':False,
              'reference':'https://doi.org/10.1175/JTECH-D-19-0134.1',
              'base_display_provenance':str(base.resolve()) if base else None,
              'sensor_transfer_note':'SEVIRI blue enhancement is DISABLED: direct AHI/ABI BTD threshold transfer produced widespread surface artifacts. Retain measured longwave cold-IR until independent cloud-mask/threshold validation.',
              'parameters':{'btd_range_k':[1,4.5],'cold_noise_reject_below_k':230,'high_ir_warm_k':280,
                            'high_ir_cold_k_tropics_poles':[200,220],'night_max_solar_elevation_deg':-6},
              'limitations':'Experimental spectral enhancement, not operational GeoColor or categorical cloud type. '
                            'Stricter land BTD bounds used everywhere; no land/sea mask, DEBRA or L2 cloud mask. '
                            'Surface emissivity/cold ground/thin or overlapping cloud may cause ambiguity. '
                            'Blue=liquid-cloud candidate signal; white=cold-IR signal, NOT confirmed convection. '
                            'Only night at both scan endpoints is displayed; day/twilight remains unrendered. '
                            'No day RGB, temporal interpolation, radiometric seam correction or gap filling.'}
    target.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    surface_path.with_suffix('.json').write_text(json.dumps({
        'kind':'static night reference with computed solar gating and missing-IR tint','source_reference':reference,
        'source_image':str(lights.resolve()),'model_utc':stamp,'projection':'EPSG:4326',
        'extent_wsen':[-180,-90,180,90],'width':width,'height':width//2,
        'is_contemporaneous_observation':False},indent=2),encoding='utf-8')
    return target
