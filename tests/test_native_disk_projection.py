"""Check shader projection against PROJ across disk and sensor page boundaries."""
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.blender_support.native_disk_material import project_ecef
from ges_next.isolation import require_writable
from pyproj import Transformer

root = Path(__file__).resolve().parents[1]
master = json.loads((root/'data/cesium_sample_20261022/native_disk/native_master.json').read_text(encoding='utf-8'))
geos = Transformer.from_crs('EPSG:4326', master['tiles'][0]['crs'], always_xy=True)
ecef = Transformer.from_crs('EPSG:4979', 'EPSG:4978', always_xy=True)
count = 0
worst = 0
for lon in range(-180, 181, 3):
    for lat in range(-84, 85, 3):
        x, y = geos.transform(lon, lat)
        u, v, visible = project_ecef(ecef.transform(lon, lat, 0))
        assert visible == (math.isfinite(x) and math.isfinite(y))
        if visible:
            worst = max(worst, math.hypot(x-u, y-v))
            # Exactly one native core owns a valid pixel, including antimeridian.
            owners = 0
            for tile in master['tiles']:
                core = tile['coreWindow']
                w = tile['extent'][0]+core['sourceX']*tile['transform'][0]
                n = tile['extent'][3]+core['sourceY']*tile['transform'][4]
                e = w+core['width']*tile['transform'][0]
                s = n+core['height']*tile['transform'][4]
                owners += w <= u < e and s <= v < n
            assert owners == 1
            count += 1
assert worst < .03  # The H9 source ellipsoid differs slightly from WGS84.
report = dict(visible_points=count, max_projection_difference_metres=worst,
              max_native_pixel_difference=worst/500, unique_core_ownership=True,
              visibility_matches_proj=True, independent_reference='PROJ / pyproj')
require_writable(root/'reports/blender_native_projection_verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report), flush=True)
