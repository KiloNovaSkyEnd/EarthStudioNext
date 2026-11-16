"""Independent observed cloud material and restrained ABI height display pilot.

No composite-luminance displacement, pressure conversion or invented heights.
Delivered HT is a retrieval, not ground truth; display compression is explicit.
"""
from pathlib import Path
import numpy as np
from .catalog import utc_time


def screened_height(height, quality, mask, mask_quality):
    h, q, m, mq = np.broadcast_arrays(height, quality, mask, mask_quality)
    valid = np.isfinite(h) & (h > 0) & (h <= 20000) & (q == 0) & (m == 1) & (mq == 0)
    return np.where(valid, h / 1000, np.nan).astype(np.float32)


def height_display(height_km, strength=.35):
    """0.3 km display shell + compressed retrieved height; NaN stays unsupported."""
    if not np.isfinite(strength) or not 0 <= strength <= .5:
        raise ValueError('Restrained relief strength must be in 0..0.5')
    h = np.asarray(height_km, np.float32)
    return .3 + np.where(np.isfinite(h) & (h > 0) & (h <= 20), h, 0) * strength


def separate_material(vis_alpha, vis_coverage, night, classes, solar_day):
    """Measured VIS display / IR display on cloudy L2 support, never ground RGB.

    Returns display RGBA, not optical thickness or a new cloud classification.
    Thin/low support is retained without a new brightness threshold.
    """
    a, cov, c, s = np.broadcast_arrays(vis_alpha, vis_coverage, classes, solar_day)
    n = np.asarray(night)
    if n.shape != a.shape + (4,):
        raise ValueError('Matching RGBA night and cloud grids required')
    if not np.isfinite(a).all() or not np.isfinite(s).all() or ((a < 0) | (a > 1) | (s < 0) | (s > 1)).any():
        raise ValueError('Finite display alpha and solar weight in 0..1 required')
    cloudy = np.isin(c, [2, 3, 5, 6, 7, 8, 9])
    day = s * cov
    na = n[..., 3].astype(np.float32) / 255
    alpha = (a * day + na * (1-day)) * cloudy
    # Keep the accepted IR palette; daytime is explicitly achromatic measured VIS.
    from .blend_night import linear_rgb, encode_rgb
    premult = (a * day)[..., None] + linear_rgb(n[..., :3]) * (na * (1-day))[..., None]
    rgb = encode_rgb(np.divide(premult, alpha[..., None], out=np.zeros_like(premult), where=alpha[..., None] > 0))
    rgb[alpha == 0] = 0
    return np.dstack([rgb, np.rint(alpha * 255).astype(np.uint8)])


def load_abi_height(files, width, satellite, start, end):
    """Read actual HT metres/DQF and BCM, each on its delivered projection grid."""
    import netCDF4
    from pyresample.geometry import AreaDefinition
    from .geosampling import inverse_global
    fields = {}; records = []
    for kind, names in [('ACHAF', ['HT', 'DQF']), ('ACMF', ['BCM', 'DQF'])]:
        paths = [Path(p) for p in files if f'ABI-L2-{kind}-' in Path(p).name]
        if len(paths) != 1:
            raise ValueError('Exactly one matching ACHA/ACM file required')
        with netCDF4.Dataset(paths[0]) as d:
            if d.platform_ID != 'G' + satellite.removeprefix('goes'):
                raise ValueError('Height platform mismatch')
            first, last = utc_time(d.time_coverage_start), utc_time(d.time_coverage_end)
            if last < first or abs((first-utc_time(start)).total_seconds()) > 1 or abs((last-utc_time(end)).total_seconds()) > 2:
                raise ValueError('Height/mask and imagery are not the same scan')
            p = d['goes_imager_projection']
            projection = dict(proj='geos', h=float(p.perspective_point_height), a=float(p.semi_major_axis),
                              b=float(p.semi_minor_axis), lon_0=float(p.longitude_of_projection_origin),
                              lat_0=float(p.latitude_of_projection_origin), sweep=p.sweep_angle_axis)
            if fields and projection != records[0]['projection']:
                raise ValueError('Height/mask projection mismatch')
            if d['x'].units != 'rad' or d['y'].units != 'rad' or (kind == 'ACHAF' and d['HT'].units != 'm'):
                raise ValueError('Delivered radian axes and metre heights required')
            x, y = [np.asarray(d[k][:], float)*projection['h'] for k in ['x', 'y']]
            if len(x) < 2 or len(y) < 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
                raise ValueError('Finite native coordinates required')
            dx, dy = np.diff(x), np.diff(y)
            if not (dx > 0).all() or not (dy < 0).all() or not np.allclose(dx, dx[0], rtol=.001) or not np.allclose(dy, dy[0], rtol=.001):
                raise ValueError('Uniform NW-to-SE delivered grid required')
            area = AreaDefinition(kind, kind, kind, projection, len(x), len(y),
                                  (x[0]-dx[0]/2, y[-1]+dy[0]/2, x[-1]+dx[0]/2, y[0]-dy[0]/2))
            arrays = [np.ma.filled(d[n][:].astype(np.float32), np.nan) for n in names]
            if any(a.shape != area.shape for a in arrays):
                raise ValueError('Height fields do not match native axes')
            mapped = inverse_global(area, arrays, width)
            fields[kind] = mapped
            records.append({'file': str(paths[0].resolve()), 'scan_start_utc': d.time_coverage_start,
                            'scan_end_utc': d.time_coverage_end, 'native_shape': list(area.shape),
                            'projection': projection, 'fields': names,
                            'dqf_meanings': d['DQF'].flag_meanings})
    h, q = fields['ACHAF']; m, mq = fields['ACMF']
    result = screened_height(h, q, m, mq)
    return result, {'sources': records, 'height_units': 'km from delivered HT metres',
                    'quality_policy': 'HT DQF=0, BCM=1 and BCM DQF=0, finite 0<HT<=20000m',
                    'mapping': 'containing delivered native pixel, no nearest-valid borrowing',
                    'valid_grid_cells': int(np.isfinite(result).sum()),
                    'uncertainty': 'No per-pixel height uncertainty consumed; DQF is not accuracy.',
                    'limits': 'Coarse retrieved cloud top, no cloud base/thickness, no parallax correction, no convection classification.'}
