"""Check full-native night pixels against independently sampled source lon/lat.

This tests geographic sampling, not coastline truth or final weather fusion.
Only small windows are read; no full native array is copied into memory.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_bounds
from rasterio.windows import Window


def main(root):
    root = Path(root)
    source = root / 'raw/references/blackmarble_2016_500m/global_500m.vrt'
    results = []
    for receipt in (root / 'processed/static_night_grids_v1').glob('*.rgba.json'):
        packing = json.loads(receipt.read_text(encoding='utf-8'))
        if packing['identity']['shape'] != [3, 22000, 22000]:
            continue
        grid_receipt = receipt.with_name(receipt.name.replace('.rgba.json', '.json'))
        grid = json.loads(grid_receipt.read_text(encoding='utf-8'))['identity']
        height, width = grid['shape']
        transform = from_bounds(*grid['extent'], width, height)
        navigation = Transformer.from_crs(grid['crs'], 'EPSG:4326', always_xy=True)
        checks = []
        with rasterio.open(source) as original, rasterio.open(receipt.with_suffix('.tif')) as packed:
            for row in np.linspace(400, height - 401, 17, dtype=int):
                for col in np.linspace(400, width - 401, 17, dtype=int):
                    x, y = transform * (int(col) + .5, int(row) + .5)
                    lon, lat = navigation.transform(x, y)
                    if not np.isfinite(lon) or not np.isfinite(lat):
                        continue
                    observed = packed.read(window=Window(int(col), int(row), 1, 1))[:, 0, 0]
                    expected = next(original.sample([(lon, lat)]))
                    checks.append(dict(row=int(row), col=int(col), lon=lon, lat=lat,
                                       original_rgb=expected.tolist(), packed_rgba=observed.tolist(),
                                       equal=bool(observed[3] == 255 and np.array_equal(observed[:3], expected))))
        results.append(dict(packed=str(receipt.with_suffix('.tif')), shape=[height, width],
                            controls=len(checks), all_equal=bool(checks and all(c['equal'] for c in checks)),
                            checks=checks))
    report = dict(results=results, all_equal=bool(results and all(r['all_equal'] for r in results)),
                  limits='Independent coordinate sampling against original NASA input; final cloud/land coastline alignment and visual acceptance remain pending.')
    (root / 'reports/full_native_night_navigation_v20.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(all_equal=report['all_equal'], controls=sum(r['controls'] for r in results))))
    if not report['all_equal']:
        raise ValueError('Full native night navigation controls failed; originals preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--root', required=True)
    main(parser.parse_args().root)
