"""Explicitly optional display effects; never satellite observations."""
import numpy as np
from .catalog import utc_time
from .solar import sun_direction


def atmosphere_config(reference_utc,day=True,airglow=False):
    return {'kind':'optional atmosphere visualization, NOT measured atmosphere',
        'reference_utc':reference_utc,'sun_direction_ecef':sun_direction(utc_time(reference_utc)).tolist(),
        'day_enabled':bool(day),'airglow_enabled':bool(airglow),
        'day_strength':.42,'airglow_strength':.05,'day_width_km':18.,
        'airglow_height_km':90.,'airglow_width_km':12.,'shell_height_km':125.,
        'day_linear_rgb':[.025,.18,.8],'airglow_linear_rgb':[.7,.25,.055],
        'limitations':'Analytic camera-limb display profiles with UTC solar weighting, not radiative transfer, retrieved gas density or contemporaneous measured airglow. No ocean recoloring. Satellite inputs and coverage untouched.'}


def validate_atmosphere(config,reference_utc):
    if config.get('kind')!='optional atmosphere visualization, NOT measured atmosphere':raise ValueError('Explicit display provenance required')
    if utc_time(config['reference_utc'])!=utc_time(reference_utc):raise ValueError('Atmosphere UTC differs from source')
    direction=np.asarray(config['sun_direction_ecef'],float)
    if direction.shape!=(3,) or not np.isfinite(direction).all() or abs(np.linalg.norm(direction)-1)>1e-5:
        raise ValueError('Finite unit Earth-fixed solar vector required')
    if not np.allclose(direction,sun_direction(utc_time(reference_utc)),atol=1e-5):raise ValueError('Solar vector differs from declared UTC')
    for field,low,high in [('day_strength',0,1),('airglow_strength',0,1),('day_width_km',1,50),
        ('airglow_height_km',70,110),('airglow_width_km',1,20),('shell_height_km',115,150)]:
        if not np.isfinite(config[field]) or not low<=config[field]<=high:raise ValueError('Invalid '+field)
    for field in ['day_linear_rgb','airglow_linear_rgb']:
        c=np.asarray(config[field],float)
        if c.shape!=(3,) or not np.isfinite(c).all() or ((c<0)|(c>1)).any():raise ValueError('Invalid effect RGB')
    return config
