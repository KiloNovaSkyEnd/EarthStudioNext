"""Compare actual rendered thickness, opacity noise and original native pixels."""
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
folder = root/'reports/layered_atmosphere_v3'
records = json.loads((folder/'new_records.json').read_text(encoding='utf-8'))
frames = {p.stem: np.asarray(Image.open(p).convert('RGB')).astype(np.float32) for p in folder.glob('*.png')}


def difference(a, b, mask=None):
    diff = np.abs(frames[a]-frames[b])
    if mask is not None:
        diff = diff[mask]
    return dict(mean_channel_error=float(diff.mean()), max_channel_error=float(diff.max()),
                p95_channel_error=float(np.percentile(diff, 95)))


record = next(r for r in records if r['name'] == 'new_blue')
w, h = record['width'], record['height']
matrix = np.asarray(record['matrix'])
xx, yy = np.meshgrid(np.arange(w)+.5, np.arange(h)+.5)
rx = (xx/w*2-1)*record['sensor_width']/2/record['lens']
ry = (1-yy/h*2)*record['sensor_width']/2*h/w/record['lens']
ray = np.stack((rx, ry, -np.ones_like(xx)), axis=-1) @ matrix[:3, :3].T
ray /= np.linalg.norm(ray, axis=-1, keepdims=True)
radii = np.array([6.378137, 6.378137, 6.356752314245])
o, d = matrix[:3, 3]/radii, ray/radii
t = -np.sum(o*d, axis=-1)/np.sum(d*d, axis=-1)
closest = o+t[:, :, None]*d
height = (np.linalg.norm(closest, axis=-1)-1)*6371
sun = np.asarray(json.loads((root/'data/exports/H9_20261020T2240_Blender_v2/package_manifest.json').read_text(encoding='utf-8'))['sun'])
normal = closest/radii
normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
day = normal @ sun > .3
mask = (height > 5) & (height < 30) & day & (t > 0)
assert mask.sum() > 100
old_noise = float(np.sqrt(np.mean((frames['old_blue_1spp'][mask]-frames['old_blue'][mask])**2)))
new_noise = float(np.sqrt(np.mean((frames['new_blue_1spp'][mask]-frames['new_blue'][mask])**2)))
assert new_noise < old_noise*.75, (old_noise, new_noise)
noise = dict(exterior_pixels=int(mask.sum()), old_1spp_vs_64spp_rmse=old_noise,
             new_1spp_vs_64spp_rmse=new_noise, reduction_fraction=1-new_noise/old_noise,
             method='Same exterior day-side pixels, tangent height 5–30km; each model compared against its own 64-sample render')
eevee_old = float(np.sqrt(np.mean((frames['old_blue_eevee_1spp'][mask]-frames['old_blue_eevee'][mask])**2)))
eevee_new = float(np.sqrt(np.mean((frames['new_blue_eevee_1spp'][mask]-frames['new_blue_eevee'][mask])**2)))
assert eevee_new < eevee_old*.5, (eevee_old, eevee_new)
noise['eevee'] = dict(old_1spp_vs_64spp_rmse=eevee_old, new_1spp_vs_64spp_rmse=eevee_new,
                     reduction_fraction=1-eevee_new/eevee_old)
off = difference('old_off', 'new_off')
assert off['mean_channel_error'] < .5 and off['p95_channel_error'] <= 2
returned = difference('new_off', 'new_off_return')
assert returned['max_channel_error'] <= 1 and returned['mean_channel_error'] < .001
# Near-vertical central cloud structure must not be covered with a broad blue wash.
central = np.zeros((h, w), dtype=bool)
central[int(h*.4):int(h*.6), int(w*.4):int(w*.6)] = True
nadir = difference('nadir_off', 'nadir_blue', central)
assert nadir['mean_channel_error'] < .5
new_halo = float(frames['new_blue'][mask].mean())
old_halo = float(frames['old_blue'][mask].mean())
assert new_halo > old_halo*1.5
switches = {name: difference(name, 'new_off') for name in ('new_blue', 'new_warm', 'new_both')}
assert all(v['max_channel_error'] > 5 for v in switches.values())

# Independent native-pixel check with the additional atmosphere disabled.
record = next(r for r in records if r['name'] == 'native_detail_off')
matrix = np.asarray(record['matrix'])
w, h = record['width'], record['height']
origin = matrix[:3, 3]
hits = []
for row in range(50, h-50, 43):
    for col in range(50, w-50, 61):
        ray = matrix[:3, :3] @ np.array([((col+.5)/w*2-1)*record['sensor_width']/2/record['lens'],
                                      (1-(row+.5)/h*2)*record['sensor_width']/2*h/w/record['lens'], -1])
        ray /= np.linalg.norm(ray)
        o, d = origin/radii, ray/radii
        a, b, c = np.dot(d, d), 2*np.dot(o, d), np.dot(o, o)-1
        point = origin+ray*((-b-math.sqrt(b*b-4*a*c))/(2*a))
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


errors = []
for (row, col, _, _), (x, y) in zip(hits, pixels):
    x, y = x-left, y-top
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x-xi, y-yi
    patch = source[yi:yi+2, xi:xi+2]
    assert patch[:, :, 3].min() > .99
    weights = np.array([[(1-fx)*(1-fy), fx*(1-fy)], [(1-fx)*fy, fx*fy]])
    rgb = (linear(patch[:, :, :3])*weights[:, :, None]).sum(axis=(0, 1))
    expected = np.where(rgb <= .0031308, rgb*12.92, 1.055*np.maximum(rgb, 0)**(1/2.4)-.055)*255
    errors.append(np.abs(frames['native_detail_off'][row, col]-expected))
errors = np.asarray(errors)
native = dict(sampled_pixels=len(errors), mean_channel_error=float(errors.mean()), p95_channel_error=float(np.percentile(errors, 95)))
assert native['mean_channel_error'] < 1 and native['p95_channel_error'] < 3
report = dict(noise=noise, baseline_surface=off, switches_off_roundtrip=returned, nadir_center=nadir,
              outside_halo_mean=dict(old=old_halo, new=new_halo), switches=switches, native_pixels=native,
              display_model_not_reference_algorithm=True)
require_writable(root/'reports/layered_atmosphere_image_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2), flush=True)
