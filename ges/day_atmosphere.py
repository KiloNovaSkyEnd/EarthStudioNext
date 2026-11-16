"""Rayleigh-only display correction; not a surface-reflectance retrieval."""
import os
import numpy as np
from pyorbital.astronomy import get_alt_az
from pyorbital.orbital import get_observer_look
from .solar import _smoothstep
from .storage import load_config

PAPER='https://repository.library.noaa.gov/view/noaa/30693/noaa_30693_DS1.pdf'


def rayleigh_corrector(platform):
    config=load_config().raw_dir/'reference/pyspectral/pyspectral.yaml'
    if not config.exists():raise ValueError('Run scripts/prepare_rayleigh.py for verified reference tables first')
    # No implicit downloads or unbudgeted RSR/LUT updates during rendering.
    os.environ['PSP_CONFIG_FILE']=str(config.resolve())
    from pyspectral.rayleigh import Rayleigh
    corrector=Rayleigh(platform,'abi',atmosphere='us-standard',aerosol_type='rayleigh_only')
    if corrector.do_download:raise ValueError('Implicit reference downloads forbidden')
    return corrector


def viewing_angles(area,when,longitude,latitude):
    lon,lat=np.broadcast_arrays(longitude,latitude)
    p=area.proj_dict
    sat_az,sat_el=get_observer_look(p['lon_0'],0,p['h']/1000,when.replace(tzinfo=None),lon,lat,0)
    sun_az=np.rad2deg(get_alt_az(when.replace(tzinfo=None),lon,lat)[1])%360
    diff=np.abs(sat_az%360-sun_az);diff=np.minimum(diff,360-diff)
    return (90-sat_el).astype(np.float32),diff.astype(np.float32)


def correction_strength(kelvin,view_zenith):
    # Miller et al 2020, section 5: 70% optical-path reduction below 233K;
    # zero reduction above 283K. No temperature-based cloud classification.
    thermal=1-.7*np.clip((283-np.asarray(kelvin))/50,0,1)
    thermal=np.where(np.isfinite(thermal),thermal,.3)
    return thermal*(1-_smoothstep(view_zenith,75,85))


def corrected_rgb(blue,red,veggie,kelvin,mid,start,end,view_zenith,azimuth,corrector):
    b,r,v=np.broadcast_arrays(blue,red,veggie)
    valid=np.isfinite(b)&np.isfinite(r)&np.isfinite(v)
    eligible=valid&(start>0)&(end>0)
    cosine=np.maximum(np.sin(np.deg2rad(mid)),np.sin(np.deg2rad(6)))
    values=[np.where(eligible,a/cosine,0).astype(np.float32) for a in [b,r,v]]
    # Pyspectral returns percent; the scene values here are fractions.
    sunz=np.asarray(90-mid,dtype=np.float32)
    strength=correction_strength(kelvin,view_zenith)
    for i,band in enumerate(['C01','C02']):
        correction=corrector.get_reflectance(sunz,view_zenith,azimuth,band)/100
        # Reduce correction near the solar horizon, as LUT assumptions fail.
        correction*=strength*(1-_smoothstep(sunz,70,90))
        values[i]=np.maximum(values[i]-correction,0)
    b,r,v=values
    # .865um is outside Pyspectral's validated 400..800nm LUT; left uncorrected.
    rgb=np.stack([r,.45*r+.10*v+.45*b,b],axis=-1)
    # Published GeoColor log display normalization; green remains CIMSS estimate.
    rgb=np.clip((np.log10(np.clip(rgb,.025,1.20))+1.6)/1.776,0,1)
    rgb=np.rint(np.where(eligible[...,None],rgb,0)*255).astype(np.uint8)
    return np.dstack([rgb,eligible.astype(np.uint8)*255]),valid,eligible


def geocolor_day_weight(elevation):
    """Miller2020 eq5/13: cos(SZA) in .1.. .3, exponent1.5."""
    return np.clip((np.sin(np.deg2rad(elevation))-.1)/.2,0,1)**1.5
