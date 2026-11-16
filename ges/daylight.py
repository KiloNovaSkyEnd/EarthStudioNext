"""Observed ABI daytime RGB; synthetic green is a declared display estimate."""
from pathlib import Path
import json
import numpy as np
from PIL import Image
from .download import read_manifest
from .render import create_satpy_scene,mask_goes_ir_quality,observation_interval
from .geosampling import inverse_global
from .solar import solar_weights
from .catalog import utc_time

REFERENCE='https://www.star.nesdis.noaa.gov/GOES/documents/ABIQuickGuide_CIMSSRGB_v2.pdf'


def abi_rgb(blue,red,veggie,elevation_mid,elevation_start,elevation_end):
    """Input measured reflectance factor (fraction), not percent or Kelvin.

    Correct solar cosine with a +6-degree lower bound; synthetic green follows
    CIMSS .45 red + .10 veggie + .45 blue. Gamma 2.2 is a display choice.
    Negative good-quality noisy reflectances are display-clipped, not missing.
    """
    b,r,v,mid,start,end=np.broadcast_arrays(*[np.asarray(a,dtype=np.float32) for a in
                                           [blue,red,veggie,elevation_mid,elevation_start,elevation_end]])
    valid=np.isfinite(b)&np.isfinite(r)&np.isfinite(v)&np.isfinite(mid)&np.isfinite(start)&np.isfinite(end)
    eligible=valid&(start>0)&(end>0)
    cosine=np.maximum(np.sin(np.deg2rad(np.where(np.isfinite(mid),mid,0))),np.sin(np.deg2rad(6)))
    rgb=np.stack([r,.45*r+.10*v+.45*b,b],axis=-1)/cosine[...,None]
    rgb=np.rint(np.clip(np.where(eligible[...,None],rgb,0),0,1)**(1/2.2)*255).astype(np.uint8)
    return np.dstack([rgb,eligible.astype(np.uint8)*255]),valid,eligible


def render_daylight(manifest,out_dir,width=8192,atmospheric=True):
    manifest=Path(manifest);out_dir=Path(out_dir);m=read_manifest(manifest)
    if not m['satellite'].startswith('goes'):raise ValueError('Only verified ABI C01/C02/C03 daylight recipe supported')
    if manifest.parent.resolve()==out_dir.resolve() or manifest.parent.resolve() in out_dir.resolve().parents:
        raise ValueError('Processed output must stay outside raw source directory')
    scene=create_satpy_scene(m['local_files'],m['satellite']);bands=['C01','C02','C03'];scene.load(bands)
    area=scene[bands[0]].attrs['area'];intervals=[];policies=[]
    for band,um in zip(bands,[.47,.64,.865]):
        a=scene[band].attrs
        if a.get('units')!='%' or abs(a['wavelength'].central-um)>.03 or a['area']!=area:
            raise ValueError('Matching measured ABI reflective bands in percent required')
        if a.get('platform_name')!='GOES-'+m['satellite'].removeprefix('goes'):
            raise ValueError('Daylight platform mismatch')
        intervals.append(observation_interval(a));policies.append(mask_goes_ir_quality(scene,m['local_files'],band))
    if len(set(intervals))!=1 or None in intervals[0]:raise ValueError('Identical verified source scan times required')
    start,end=map(utc_time,intervals[0]);mid=start+(end-start)/2
    if end<start:raise ValueError('Reversed scan')
    import dask
    if atmospheric:
        from .day_atmosphere import rayleigh_corrector,corrected_rgb,viewing_angles
        scene.load(['C13']);mask_goes_ir_quality(scene,m['local_files'],'C13')
        if scene['C13'].attrs['area']!=area or observation_interval(scene['C13'].attrs)!=intervals[0]:
            raise ValueError('Rayleigh cloud-path proxy requires same scan/grid C13')
        corrector=rayleigh_corrector(scene['C01'].attrs['platform_name'])
    native=dask.compute(*[scene[b].data for b in bands])
    b,r,v=inverse_global(area,[np.ma.filled(a,np.nan)/100 for a in native],width)
    lw=inverse_global(area,[np.ma.filled(scene['C13'].compute().values,np.nan)],width)[0] if atmospheric else None
    rgba=np.zeros((width//2,width,4),dtype=np.uint8);coverage=np.zeros(rgba.shape[:2],dtype=np.uint8)
    viewmap=np.zeros_like(coverage)
    lon=-180+(np.arange(width)+.5)*360/width
    for row in range(0,width//2,128):
        sl=slice(row,min(row+128,width//2));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
        first=solar_weights(start,lon[None,:],lat[:,None]).elevation_deg
        last=solar_weights(end,lon[None,:],lat[:,None]).elevation_deg
        middle=solar_weights(mid,lon[None,:],lat[:,None]).elevation_deg
        if atmospheric:
            from .solar import _smoothstep
            view,azimuth=viewing_angles(area,mid,lon[None,:],lat[:,None])
            rgba[sl],valid,_=corrected_rgb(b[sl],r[sl],v[sl],lw[sl],middle,first,last,view,azimuth,corrector)
            viewmap[sl]=np.rint((1-_smoothstep(view,65,80))*255).astype(np.uint8)
        else:rgba[sl],valid,_=abi_rgb(b[sl],r[sl],v[sl],middle,first,last)
        coverage[sl]=valid.astype(np.uint8)*255
    out_dir.mkdir(parents=True,exist_ok=True);p=out_dir/'goes_daylight.png'
    Image.fromarray(rgba).save(p);Image.fromarray(coverage).save(out_dir/'goes_daylight_visible_coverage.png')
    Image.fromarray(rgba[...,3]).save(out_dir/'goes_daylight_eligible.png')
    if atmospheric:Image.fromarray(viewmap).save(out_dir/'goes_daylight_view_weight.png')
    metadata={'product':'daylight-rgb','display_recipe':'abi-cimss-three-band-approx-v1',
        'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':width,'height':width//2,
        'satellite':m['satellite'],'observed_utc':m['observed_utc'],
        'scan_start_utc':intervals[0][0],'scan_end_utc':intervals[0][1],
        'source_manifest':str(manifest.resolve()),'bands':bands,'source_band_units':'percent; divided by 100',
        'navigation_recipe':'inverse-native-geos-pixel-footprint-v1','quality_policy':policies,
        'green_recipe':'.45*C02 + .10*C03 + .45*C01; synthetic green, not a measured green channel',
        'solar_correction':'divide reflectance factor by scan-midpoint solar cosine, bounded below by sin(6 degrees)',
        'daylight_gate':'solar elevation strictly >0 at BOTH scan endpoints',
        'display_gamma':2.2,'source_visible_coverage':'goes_daylight_visible_coverage.png',
        'daylight_pixels':int((rgba[...,3]>0).sum()),'is_cloud_only_layer':False,
        'reference':REFERENCE,'limitations':'Approximate daytime RGB including land, ocean, clouds, snow, smoke and aerosols; not a cloud mask. No Rayleigh/aerosol correction or sharpening. Delivered MCMIP grid is 2km, not native 500m red resolution. No night VIS or synthesized observations.'}
    if atmospheric:
        from .day_atmosphere import PAPER
        metadata.update(display_recipe='abi-rayleigh-cold-cloud-log-v2',display_gamma=None,
            display_scaling='clip reflectance .025..1.20; normalize log10 with -1.6.. .176 (Miller2020)',
            rayleigh=f"Pyspectral rayleigh_only us-standard with actual {scene['C01'].attrs['platform_name']} ABI RSR, C01/C02; C03 .865um outside LUT domain, uncorrected",
            cloud_path='C13 233..283K reduces Rayleigh by 70%..0%; not a cloud-type retrieval',
            angular_reduction='Rayleigh fades at view zenith75..85 and solar zenith70..90deg',
            source_view_weight='goes_daylight_view_weight.png',
            reference=PAPER,
            limitations='Approximate RGB with CIMSS synthetic green, not full CIRA SHAC. Rayleigh-only standard atmosphere; no aerosol retrieval, NIR correction or sharpening. Strict DQF0 preserved; invalid visible remains missing. Native MCMIP2km, not500m. No inferred cloud opacity/height.')
    p.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8');return p
