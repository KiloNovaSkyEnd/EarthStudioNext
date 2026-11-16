"""Exact nonzero compositor demand, with conservative display-operation halo.

Keep ORIGINAL full model inputs, tile grid, overlap weights and accumulation
order. Select whole original tiles, never crop model context or renormalize
away a tile contributing to a required pixel. Native 32-pixel halo covers the
pure recipe's five-pixel erosion + finite Gaussian radius 8, 2x bilinear and
JPEG 4:4:4 block dependency. Full final-image equality remains a release gate.
"""
from pathlib import Path
import numpy as np
from scipy.ndimage import maximum_filter

HALO = 32


def native_mask(solar, support, mode, high=None, low=None, halo=HALO):
    if mode not in ('ai-vis', 'ai-vis-ir'):
        raise ValueError('Optional night mode required')
    if solar.dtype != np.uint16 or support.dtype != np.uint8:
        raise ValueError('Expected original quantized solar/support')
    if solar.ndim != 2 or solar.shape != support.shape or any(n % 2 for n in solar.shape):
        raise ValueError('Expected matching even grids')
    if mode == 'ai-vis-ir':
        if high is None or low is None or high.shape != solar.shape or low.shape != solar.shape:
            raise ValueError('Missing original cloud fields')
        if high.dtype != np.uint8 or low.dtype != np.uint8:
            raise ValueError('Unexpected cloud precision')
    if type(halo) is not int or halo < HALO:
        raise ValueError('Required display context may not be reduced')
    h, w = solar.shape
    required = np.zeros((h//2, w//2), bool)
    for y in range(0, h, 250):
        stop = min(y+250, h)
        active = (solar[y:stop] != 65535) & (support[y:stop] != 0)
        if mode == 'ai-vis-ir':
            active &= (high[y:stop] != 0) | (low[y:stop] != 0)
        required[y//2:stop//2] = active.reshape((stop-y)//2, 2, w//2, 2).any(axis=(1, 3))
    return maximum_filter(required, size=2*halo+1, mode='constant', cval=0)


def required_native(work, mode):
    work = Path(work)
    maps = {}
    try:
        for name in ('solar_branch', 'support') + (('high_branch', 'low_branch') if mode == 'ai-vis-ir' else ()):
            maps[name] = np.load(work/(name+'.npy'), mmap_mode='r')
        if maps['solar_branch'].shape != (11000, 11000):
            raise ValueError('Demand requires the original 11K grid')
        return native_mask(maps['solar_branch'], maps['support'], mode,
                           maps.get('high_branch'), maps.get('low_branch'))
    finally:
        for value in maps.values():
            value._mmap.close()


def tile_coordinates(required, starts, size):
    if required.ndim != 2 or required.dtype != bool:
        raise ValueError('Boolean native demand required')
    return [(x, y) for y in starts for x in starts
            if required[y:y+size, x:x+size].any()]


def configure(work, utc, mode, config_path=None):
    """Gate at the per-scan boundary, excluding every pre-activation job.

    Pure execution policy. Does not edit job/queue/plan or relax observation
    checks. A missing/disabled policy preserves the original full inference.
    """
    import json, os
    work=Path(work).resolve()
    root=Path(__file__).resolve().parents[3]
    config_path=Path(config_path) if config_path is not None else root/'resources/performance/night_demand_activation.json'
    enabled=False;reason='not-activated'
    if config_path.exists():
        cfg=json.loads(config_path.read_text(encoding='utf-8'))
        if cfg.get('enabled') is True:
            if cfg.get('schema')!='earthstudio.night_demand.activation.v1':
                raise ValueError('Unknown night demand activation schema')
            package=next((p for p in (work,*list(work.parents)[:3]) if (p/'job.json').is_file()),None)
            if package is None:raise ValueError('Night demand lacks production job binding')
            path=package/'job.json';job=json.loads(path.read_text(encoding='utf-8'))
            if job.get('utc')!=utc or job.get('night_recipe',{}).get('mode')!=mode:
                raise ValueError('Night demand job UTC/recipe mismatch')
            profile=job.get('quality')==95 and job.get('night_metres')==1000 and mode in ('ai-vis','ai-vis-ir')
            old_job=path.stat().st_mtime_ns < cfg['activated_ns'] or str(package) in cfg.get('excluded_packages',[])
            enabled=profile and not old_job
            reason='new-scan-boundary' if enabled else ('pre-activation-scan' if old_job else 'unqualified-profile')
    os.environ['EARTHSTUDIO_NIGHT_MODE']=mode
    os.environ['EARTHSTUDIO_NIGHT_DEMAND']='1' if enabled else '0'
    return dict(revision='night-demand-v1',enabled=enabled,reason=reason)
