"""Offline feasibility probe, not a production recipe or UI implementation.

Read an existing observed VIS crop; verify configurable Satpy enhancement,
fixed-parameter tiled equivalence, source immutability, and alpha isolation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import satpy
import trollimage
import xarray as xr
from satpy.enhancements.contrast import gamma, stretch
from satpy.enhancements.enhancer import get_enhanced_image

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def enhance(values, recipe):
    # Isolate the scientific array; never enhance validity/coverage alongside RGB.
    image = get_enhanced_image(xr.DataArray(values.copy(), dims=('y', 'x')), enhance=False)
    stretch(image, stretch='crude', min_stretch=recipe['black'], max_stretch=recipe['white'])
    gamma(image, gamma=recipe['gamma'])
    return np.asarray(image.data.compute())[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    source = ROOT / 'data/processed/hinnamnor_geocolor_v1/0830/observed_inputs.npz'
    metadata = source.with_name('official_metadata.json')
    before = {str(p.relative_to(ROOT)): sha(p) for p in (source, metadata)}
    with np.load(source) as arrays:
        values = arrays['B03_fraction_1km'][700:1212, 1100:1612].copy()
    original_bytes = values.tobytes()
    records = []
    for exponent in (1., 1.7, 2.2):
        recipe = json.loads(json.dumps({'black': 0., 'white': 1., 'gamma': exponent}))
        start = time.perf_counter()
        full = enhance(values, recipe)
        elapsed = time.perf_counter() - start
        tiled = np.empty_like(full)
        for y in range(0, len(values), 128):
            for x in range(0, values.shape[1], 128):
                tiled[y:y+128, x:x+128] = enhance(values[y:y+128, x:x+128], recipe)
        equal = np.array_equal(full, tiled, equal_nan=True)
        missing_equal = np.array_equal(np.isnan(full), np.isnan(values))
        assert equal and missing_equal and original_bytes == values.tobytes()
        records.append(dict(recipe=recipe, shape=list(full.shape), dtype=str(full.dtype),
                            tile_equivalence=equal, missing_mask_equal=missing_equal,
                            processing_seconds=elapsed,
                            output_sha256=hashlib.sha256(full.tobytes()).hexdigest()))
    assert len({r['output_sha256'] for r in records}) == 3

    # Explicit synthetic API contract probe. Not observation data or imagery.
    la = np.array([[[.25, np.nan]], [[.25, 0.]]], dtype=np.float32)
    image = get_enhanced_image(xr.DataArray(la, dims=('bands', 'y', 'x'),
                                          coords={'bands': ['L', 'A']}), enhance=False)
    gamma(image, gamma=2.)
    result = np.asarray(image.data.compute())
    assert result[1, 0, 0] == .5  # Direct gamma also modifies an explicit alpha band.
    gray = enhance(la[0], {'black': 0., 'white': 1., 'gamma': 2.})
    isolated = np.stack([gray, la[1].copy()])
    assert isolated[1].tobytes() == la[1].tobytes()
    assert np.array_equal(np.isnan(gray), np.isnan(la[0]))
    after = {str(p.relative_to(ROOT)): sha(p) for p in (source, metadata)}
    assert before == after
    report = dict(satpy_version=satpy.__version__, trollimage_version=trollimage.__version__,
                  utc=json.loads(metadata.read_text(encoding='utf-8'))['nominal_utc'],
                  scope='Existing 1km averaged regional VIS cache, not original 500m, RGB or globe.',
                  source_sha256=before, source_files_unchanged=True,
                  observed_nan_pixels=int(np.isnan(values).sum()), records=records,
                  synthetic_contract_probe=dict(direct_gamma_alpha_before=.25,
                                                direct_gamma_alpha_after=float(result[1, 0, 0]),
                                                isolated_alpha_byte_exact=True,
                                                isolated_nan_mask_preserved=True),
                  limitations='No GUI/GPU latency, full-global, sequence, or Blender color match benchmark.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
