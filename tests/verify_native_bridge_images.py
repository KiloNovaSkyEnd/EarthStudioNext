"""Actual rendered switch differences and native pixel geographic/color checks."""
import json
import math
from pathlib import Path
import sys
import numpy as np
from PIL import Image
import rasterio
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.native_disk_material import project_ecef
from ges_next.isolation import require_writable

root = Path(__file__).resolve().parents[1]
folder = root/'reports/blender_native_bridge'
records = json.loads((folder/'render_records.json').read_text(encoding='utf-8'))
base = np.array(Image.open(folder/'rim_00_off.png').convert('RGB')).astype(np.int16)
switches = {}
for label in ('rim_10_blue', 'rim_01_warm', 'rim_11_both', 'rim_00_return'):
    arr = np.array(Image.open(folder/(label+'.png')).convert('RGB')).astype(np.int16)
    diff = np.abs(arr-base)
    switches[label] = dict(changed_pixels=int(np.any(diff, axis=-1).sum()), max_channel_difference=int(diff.max()))
assert switches['rim_10_blue']['changed_pixels'] > 100
assert switches['rim_01_warm']['changed_pixels'] > 100
assert switches['rim_11_both']['changed_pixels'] > max(switches[x]['changed_pixels'] for x in ('rim_10_blue', 'rim_01_warm'))
# GPU rendering can round a channel differently at the last 8-bit step.
# Permit at most 5 pixels/1 code value, not a residual halo.
assert switches['rim_00_return']['changed_pixels'] <= 5
assert switches['rim_00_return']['max_channel_difference'] <= 1

record = next(r for r in records if r['name'] == 'native_detail_1080p')
rgb = np.array(Image.open(folder/'native_detail_1080p.png').convert('RGB')).astype(float)
matrix = np.asarray(record['matrix'])
w, h = record['width'], record['height']
radii = np.array([6.378137, 6.378137, 6.356752314245])
origin = matrix[:3, 3]
hits = []
for row in range(50, h-50, 43):
    for col in range(50, w-50, 61):
        ray = matrix[:3, :3] @ np.array([((col+.5)/w*2-1)*record['sensor_width']/2/record['lens'],
                                       (1-(row+.5)/h*2)*record['sensor_width']/2*h/w/record['lens'], -1])
        ray /= np.linalg.norm(ray)
        o, d = origin/radii, ray/radii
        a, b, c = np.dot(d, d), 2*np.dot(o, d), np.dot(o, o)-1
        disc = b*b-4*a*c
        assert disc > 0
        point = origin+ray*((-b-math.sqrt(disc))/(2*a))
        x, y, visible = project_ecef(point*1e6)
        assert visible
        hits.append((row, col, x, y))

with rasterio.open(root/'data/cesium_sample_20261022/native_disk/master.vrt') as dataset:
    pixels = [((x-dataset.transform.c)/dataset.transform.a-.5, (y-dataset.transform.f)/dataset.transform.e-.5) for _, _, x, y in hits]
    left, top = np.floor(np.min(pixels, axis=0)).astype(int)
    right, bottom = np.ceil(np.max(pixels, axis=0)).astype(int)+2
    source = dataset.read(window=Window(left, top, right-left, bottom-top)).transpose(1, 2, 0)/255

def linear(value):
    return np.where(value <= .04045, value/12.92, ((value+.055)/1.055)**2.4)

def srgb(value):
    return np.where(value <= .0031308, value*12.92, 1.055*np.maximum(value, 0)**(1/2.4)-.055)

errors = []
for (row, col, _, _), (x, y) in zip(hits, pixels):
    x, y = x-left, y-top
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x-xi, y-yi
    patch = source[yi:yi+2, xi:xi+2]
    assert patch[:, :, 3].min() > .99
    weights = np.array([[(1-fx)*(1-fy), fx*(1-fy)], [(1-fx)*fy, fx*fy]])
    expected = srgb((linear(patch[:, :, :3])*weights[:, :, None]).sum(axis=(0, 1)))*255
    errors.append(np.abs(rgb[row, col]-expected))
errors = np.asarray(errors)
native = dict(sampled_pixels=len(errors), mean_absolute_channel_error=float(errors.mean()),
              p95_channel_error=float(np.percentile(errors, 95)), max_channel_error=float(errors.max()),
              method='Independent camera rays -> WGS84 intersection -> native raster bilinear linear-light RGB; render includes subpixel AA')
assert native['mean_absolute_channel_error'] < 3, native
assert native['p95_channel_error'] < 8, native
report = dict(switches=switches, native_pixel_comparison=native, renders_verified=len(records),
              source_utc='2026-10-20T22:40:00Z', weather_animated=False)
require_writable(root/'reports/blender_native_image_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2), flush=True)
