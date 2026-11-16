"""Separate low-liquid evidence from continuous observed-radiance display."""
import numpy as np


def daylight_material(reflectance,probability):
    """Retain measured bright-cloud tone, independently approximate opacity.

    Smooth exposure compression, no hard white clipping or invented detail.
    This is a display transfer, not a cloud optical-depth retrieval.
    """
    r,p=np.broadcast_arrays(np.asarray(reflectance,np.float32),np.asarray(probability,np.float32))
    valid=np.isfinite(r)&(r>=0)&np.isfinite(p)&(p>=0)&(p<=1)
    r=np.where(valid,r,0);p=np.where(valid,p,0)
    color=(1-np.exp(-1.8*r))**(1/2.2)
    alpha=(1-np.exp(-5*r))*p
    return color.astype(np.float32),alpha.astype(np.float32)


def low_liquid_confidence(mask,mask_q,phase,phase_q,height_km,error_km,height_q):
    arrays=[np.asarray(v) for v in (mask,mask_q,phase,phase_q,height_km,error_km,height_q)]
    if any(v.shape!=arrays[0].shape for v in arrays):raise ValueError('Same native grids required')
    mask,mq,phase,pq,h,e,hq=arrays
    eligible=np.isin(mask,[2,3])&(mq==0)&np.isin(phase,[1,2])&(pq==0)&(hq==0)&np.isfinite(h)&np.isfinite(e)&(h>0)&(e>=0)&(e<=3)
    strict=eligible&(h+e<=3)
    nominal=eligible&(h<=3)&~strict
    return np.where(strict,1.,np.where(nominal,.35,0)).astype(np.float32)


def screen_confident_clear(probability,mask,mask_quality):
    """Display-only: a nonzero posterior must not paint a QF0 clear surface as cloud.

    Delivered arrays are never modified. Probably-clear remains uncertain;
    probably-cloudy/cloudy and all unrelated quality states are unchanged.
    """
    p,m,q=[np.asarray(v) for v in (probability,mask,mask_quality)]
    if p.shape!=m.shape or p.shape!=q.shape:raise ValueError('Matching native grids required')
    return np.where((m==0)&(q==0),0,p)


def _low_cloud_chroma(color,strength):
    """Bounded display tint only; preserve weighted RGB brightness, not radiance.

    Strength 1 reproduces the existing palette exactly. This does not modify
    class confidence, observed texture, visibility, or cloud opacity.
    """
    if not np.isscalar(strength) or not np.isfinite(strength) or not .8<=strength<=1:
        raise ValueError('Low-cloud tint strength must be finite and in 0.8..1')
    if strength==1:return color
    grey=np.sum(color*np.array([.2126,.7152,.0722],np.float32),axis=-1,keepdims=True)
    return grey+np.float32(strength)*(color-grey)


def night_material(kelvin,probability,low_confidence,*,low_cloud_tint_strength=1.):
    """Measured IR texture. Low classification adjusts tint, never gates clouds.

    Probability is delivered L2 confidence, not measured optical depth. All
    alpha and blue tint are labelled display transfers, not night VIS retrieval.
    """
    t,p,low=[np.asarray(v,np.float32) for v in (kelvin,probability,low_confidence)]
    if t.shape!=p.shape or t.shape!=low.shape:raise ValueError('Same native grids required')
    valid=np.isfinite(t)&(t>=100)&(t<=350)&np.isfinite(p)&(p>=0)&(p<=1)
    t=np.where(valid,t,300);p=np.where(valid,p,0);low=np.clip(low,0,1)
    cold=np.clip((300-t)/130,0,1)
    neutral_alpha=.08+.90*cold**1.15
    thermal=np.clip((305-t)/65,0,1)
    alpha=np.maximum(neutral_alpha,(.35+.45*thermal)*low)*p
    neutral=(.42+.43*cold)[...,None]*np.ones(3,np.float32)
    blue=_low_cloud_chroma((.65+.35*thermal)[...,None]*np.array([.55,.75,.98],np.float32),low_cloud_tint_strength)
    rgb=neutral*(1-low[...,None])+blue*low[...,None]
    return rgb.astype(np.float32),alpha.astype(np.float32)


def spectral_night_material(longwave,shortwave,probability,low_confidence,eligible,*,low_cloud_tint_strength=1.):
    """Restore observed LW-SW texture without using spectral difference as class.

    Missing/day-contaminated SW falls back to LW. Low-class rejection never
    cuts the neutral cloud material; classification only controls tint/detail.
    """
    from .cloud_evidence import low_cloud_texture
    t,sw,p,low,eligible=np.broadcast_arrays(longwave,shortwave,probability,low_confidence,eligible)
    rgb,alpha=night_material(t,p,low,low_cloud_tint_strength=low_cloud_tint_strength)
    paired=np.isfinite(t)&(t>=100)&(t<=350)&np.isfinite(sw)&(sw>=100)&(sw<=350)&np.isfinite(p)&(p>=0)&(p<=1)&eligible
    visibility,color=low_cloud_texture(t,sw)
    color=_low_cloud_chroma(color,low_cloud_tint_strength)
    neutral_rgb,neutral_alpha=night_material(t,p,np.zeros_like(low))
    selected=np.where(paired,np.clip(low,0,1),0).astype(np.float32)
    new_rgb=neutral_rgb*(1-selected[...,None])+color*selected[...,None]
    # Supported low cloud remains visible even when BTD is weak. Spectral
    # contrast is measured, and its continuous response is not a cloud mask.
    thermal=np.clip((305-np.where(np.isfinite(t),t,305))/65,0,1)
    low_alpha=np.maximum(visibility,.20+.35*thermal)*p
    new_alpha=np.maximum(neutral_alpha,low_alpha*selected)
    return np.where(paired[...,None],new_rgb,rgb).astype(np.float32),np.where(paired,new_alpha,alpha).astype(np.float32)


def evidence_tinted_night_material(longwave,shortwave,probability,low_confidence,eligible,*,low_cloud_tint_strength=.85):
    """Opt-in GeoColor-inspired tint weight; never use this as a new cloud mask.

    Keep the existing spectral material's opacity exactly. Only qualified L2
    low cloud can be blue, with continuous measured B13-B07/4 K weighting.
    Missing/day-contaminated SW retains the existing measured LW fallback.
    No spatial blur, class extension, missing-data fill or texture synthesis.
    """
    from .cloud_evidence import low_cloud_texture
    t,sw,p,low,night=np.broadcast_arrays(longwave,shortwave,probability,low_confidence,eligible)
    fallback,alpha=spectral_night_material(t,sw,p,low,night,low_cloud_tint_strength=low_cloud_tint_strength)
    neutral,_=night_material(t,p,np.zeros_like(low))
    _,blue=low_cloud_texture(t,sw);blue=_low_cloud_chroma(blue,low_cloud_tint_strength)
    paired=night&np.isfinite(t)&np.isfinite(sw)&(sw>=100)&(sw<=350)&(t>=100)&(t<=350)
    weight=np.where(paired&(t>=230),np.clip(low,0,1)*np.clip((t-sw)/4,0,1),0).astype(np.float32)
    rgb=neutral*(1-weight[...,None])+blue*weight[...,None]
    return np.where(paired[...,None],rgb,fallback).astype(np.float32),alpha
