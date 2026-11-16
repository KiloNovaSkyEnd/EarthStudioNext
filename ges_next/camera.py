"""ECEF camera contract: world axes are X=lon0, Y=lon90E, Z=north.

Blender local camera axes are +X right, +Y up, -Z forward.
No heading/pitch/roll conversion or spherical approximation is applied.
"""
import math
from datetime import datetime


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def vector(value):
    if not isinstance(value, list) or len(value) != 3 or not all(type(x) in (int,float) and math.isfinite(x) for x in value):
        raise ValueError('Expected finite three-vector')
    return value


def basis(direction, up):
    d, u = vector(direction), vector(up)
    if abs(dot(d,d)-1) > 1e-5 or abs(dot(u,u)-1) > 1e-5 or abs(dot(d,u)) > 1e-5:
        raise ValueError('Camera orientation must be orthonormal')
    return cross(d,u), u, [-x for x in d]


def validate(track):
    if (track.get('schema'),track.get('earthModel'),track.get('coordinates')) != ('earthstudio.camera.v1','WGS84','ECEF_METERS'):
        raise ValueError('Unsupported camera/earth coordinates')
    if type(track.get('fps')) not in (int,float) or not math.isfinite(track['fps']) or not 1 <= track['fps'] <= 120 or not isinstance(track.get('samples'),list) or not 1 <= len(track['samples']) <= 1000000:
        raise ValueError('Expected 1–1000000 camera samples at project fps (1–120)')
    previous, dimensions = -1, None
    for sample in track['samples']:
        seconds = sample['seconds']
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or not previous < seconds or seconds < 0:
            raise ValueError('Camera times must be finite and increasing')
        previous = seconds
        vector(sample['position']); basis(sample['direction'],sample['up'])
        width,height = sample['width'],sample['height']
        if any(type(x) is not int or not 1 <= x <= 16384 for x in [width,height]):
            raise ValueError('Invalid frame dimensions')
        if dimensions is not None and dimensions != (width,height):
            raise ValueError('Canvas resized during recording; record again with fixed dimensions')
        dimensions = width,height
        fov,aspect = sample['verticalFov'],sample['aspect']
        if not all(type(x) in (int,float) and math.isfinite(x) for x in [fov,aspect]) or not 0 < fov < math.pi or abs(aspect-width/height) > 1e-4:
            raise ValueError('Invalid frustum/aspect')
        utc = sample.get('utc')
        if utc is not None:
            if not isinstance(utc,str) or not utc.endswith('Z'):
                raise ValueError('Observation time must be UTC')
            datetime.fromisoformat(utc.replace('Z','+00:00'))
    return track


def horizontal_lens_mm(sample, sensor_width=36):
    return sensor_width/(2*math.tan(sample['verticalFov']/2)*sample['aspect'])
