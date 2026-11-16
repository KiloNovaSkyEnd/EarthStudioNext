"""Geometric solar lighting and display weights, never satellite observations.

Astronomy: https://pyorbital.readthedocs.io/en/stable/ . No atmospheric
refraction, terrain shadow, cloud height or radiative-transfer model is implied.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

import numpy as np
from PIL import Image
from pyorbital import astronomy, __version__ as pyorbital_version


def _utc(when: datetime) -> datetime:
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError('Solar calculations require an explicit UTC/timezone timestamp')
    return when.astimezone(timezone.utc)


def sun_direction(when: datetime) -> np.ndarray:
    """Unit Earth-fixed vector: X=(0E,0N), Y=(90E,0N), Z=north pole."""
    utc = _utc(when).replace(tzinfo=None)  # Pyorbital expects naive UTC internally.
    ra, dec = astronomy.sun_ra_dec(utc)
    longitude = ra - astronomy.gmst(utc)
    return np.array([np.cos(dec) * np.cos(longitude),
                     np.cos(dec) * np.sin(longitude), np.sin(dec)])


@dataclass(frozen=True)
class SolarWeights:
    elevation_deg: np.ndarray
    surface_direct: np.ndarray
    day_cloud: np.ndarray
    night_ir: np.ndarray
    city_lights: np.ndarray


def _smoothstep(value, low, high):
    t = np.clip((value - low) / (high - low), 0, 1)
    return t * t * (3 - 2 * t)


def solar_weights(when: datetime, longitude, latitude,
                  day_full_elevation: float = 6.0,
                  lights_full_elevation: float = -6.0) -> SolarWeights:
    """Broadcast geographic degrees into independent lighting/display weights.

    VIS contribution is zero at/below the geometric horizon, becoming fully
    selected at +6 degrees by default. IR supplies the complementary display
    weight, independent of surface lighting. City lights fade from -6 to 0.
    These smoothstep ranges are display choices, not measured illumination.
    Weights do NOT imply data availability: retain each source's actual alpha
    mask and timestamp when compositing. Never fill missing VIS with fake VIS.
    """
    _utc(when)
    if not np.isfinite(day_full_elevation) or not 0 < day_full_elevation <= 90:
        raise ValueError('day_full_elevation must be in (0, 90] degrees')
    if not np.isfinite(lights_full_elevation) or not -90 <= lights_full_elevation < 0:
        raise ValueError('lights_full_elevation must be in [-90, 0) degrees')
    lon, lat = np.broadcast_arrays(np.asarray(longitude, dtype=np.float64),
                                   np.asarray(latitude, dtype=np.float64))
    if (not np.isfinite(lon).all() or not np.isfinite(lat).all()
            or (np.abs(lon) > 180).any() or (np.abs(lat) > 90).any()):
        raise ValueError('Finite longitude [-180,180] and latitude [-90,90] required')
    lon, lat = np.deg2rad(lon), np.deg2rad(lat)
    sun = sun_direction(when)
    cosine = np.clip(np.cos(lat) * (np.cos(lon) * sun[0] + np.sin(lon) * sun[1])
                     + np.sin(lat) * sun[2], -1, 1)
    elevation = np.rad2deg(np.arcsin(cosine))
    day = _smoothstep(elevation, 0, day_full_elevation)
    return SolarWeights(elevation.astype(np.float32),
                        np.maximum(cosine, 0).astype(np.float32),
                        day.astype(np.float32), (1 - day).astype(np.float32),
                        (1 - _smoothstep(elevation, lights_full_elevation, 0)).astype(np.float32))


def global_solar_weights(when: datetime, width: int = 2048) -> SolarWeights:
    """Pixel centers of the same north-first 2:1 grid used by GES imagery."""
    if not isinstance(width, int) or not 512 <= width <= 8192 or width % 2:
        raise ValueError('Width must be an even integer from 512 to 8192')
    longitude = -180 + (np.arange(width) + 0.5) * 360 / width
    latitude = 90 - (np.arange(width // 2) + 0.5) * 360 / width
    return solar_weights(when, longitude[None, :], latitude[:, None])


def export_solar_weights(when: datetime, out_dir: Path, width: int = 2048) -> Path:
    """Derived diagnostic NPZ + day-weight PNG + provenance; no cloud imagery."""
    utc = _utc(when)
    weights = global_solar_weights(utc, width)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Microseconds prevent different requested instants sharing one filename.
    stem = f'solar_{utc:%Y%m%dT%H%M%S%fZ}_{width}'
    target = out_dir / (stem + '.npz')
    np.savez_compressed(target, **vars(weights), sun_direction=sun_direction(utc))
    preview = out_dir / (stem + '_day_weight.png')
    Image.fromarray(np.rint(weights.day_cloud * 255).astype(np.uint8)).save(preview)
    metadata = {
        'kind': 'computed solar weights, NOT observed satellite/cloud pixels',
        'model_utc': utc.isoformat().replace('+00:00', 'Z'),
        'projection': 'EPSG:4326', 'extent_wsen': [-180, -90, 180, 90],
        'width': width, 'height': width // 2, 'top_row': 'north',
        'astronomy': f'pyorbital {pyorbital_version}',
        'reference': 'https://pyorbital.readthedocs.io/en/stable/',
        'sun_direction_xyz': sun_direction(utc).tolist(),
        'day_cloud_transition_elevation_deg': [0, 6],
        'city_lights_transition_elevation_deg': [-6, 0],
        'preview': preview.name,
        'limitations': 'Geometric sun; no refraction, cloud height or terrain shadows. '
                       'Transition widths are display choices. No source coverage or '
                       'cloud imagery is created; source masks/times remain mandatory.',
    }
    target.with_suffix('.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    return target
