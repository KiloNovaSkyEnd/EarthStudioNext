"""Bounded native-sized JPEG derivative probe; never replace retained pixels."""
from pathlib import Path
import hashlib
import json
import math
import time

import numpy as np
from PIL import Image
import rasterio


def main():
    root = Path(__file__).resolve().parents[1]
    package = root / 'data/exports/H9_20261020_12h_Blender_v1'
    out = root / 'reports/native_cache_research_20261023/jpeg_probe'
    out.mkdir(exist_ok=False)
    manifest = json.loads((package / 'sequence_manifest.json').read_text())
    entries = {e['path']: e for e in manifest['files']}
    rows = []
    for index in (1, 73):
        relative = f'assets/native_05500_05500/weather_{index:04d}.tif'
        source = package / relative
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        assert before == entries[relative]['sha256']
        with rasterio.open(source) as dataset:
            rgba = np.moveaxis(dataset.read(), 0, -1)
            assert rgba.dtype == np.uint8 and rgba.shape[2] == 4
        rgb = np.ascontiguousarray(rgba[:, :, :3])
        alpha = rgba[:, :, 3]
        alpha_path = out / f'{index:04d}_alpha.png'
        Image.fromarray(alpha).save(alpha_path, compress_level=6)
        assert np.array_equal(np.asarray(Image.open(alpha_path)), alpha)
        image = Image.fromarray(rgb)
        for quality, subsampling in ((95, 2), (95, 0), (98, 0)):
            target = out / f'{index:04d}_q{quality}_s{subsampling}.jpg'
            started = time.perf_counter()
            image.save(target, quality=quality, subsampling=subsampling, optimize=True)
            write_seconds = time.perf_counter() - started
            with Image.open(target) as encoded:
                assert encoded.size == image.size
                reconstructed = np.asarray(encoded.convert('RGB'))
            squared = absolute = changed = count = maximum = 0
            for top in range(0, rgb.shape[0], 256):
                valid = alpha[top:top + 256] > 0
                delta = (rgb[top:top + 256].astype(np.int16) - reconstructed[top:top + 256].astype(np.int16))[valid]
                values = np.abs(delta)
                count += values.size
                squared += np.square(delta.astype(np.float64)).sum()
                absolute += values.sum()
                changed += np.count_nonzero(values)
                maximum = max(maximum, int(values.max(initial=0)))
            mse = float(squared / count)
            row = dict(nominal_index=index, utc=manifest['nodes'][index - 1]['utc'],
                       shape=list(rgb.shape), source_tiff_bytes=source.stat().st_size,
                       quality=quality, chroma_subsampling='4:4:4' if subsampling == 0 else '4:2:0',
                       jpeg_bytes=target.stat().st_size, alpha_png_bytes=alpha_path.stat().st_size,
                       combined_bytes=target.stat().st_size + alpha_path.stat().st_size,
                       encode_seconds=write_seconds, valid_rgb_channel_mae=float(absolute / count),
                       valid_rgb_psnr_db=10 * math.log10(255 ** 2 / mse) if mse else None,
                       maximum_valid_channel_difference=maximum,
                       changed_valid_channel_fraction=float(changed / count),
                       pixel_exact=mse == 0, dimensions_preserved=True,
                       alpha_sidecar_exact=True, derivative=str(target.relative_to(root)))
            rows.append(row)
            print('JPEG_NATIVE_SAMPLE', json.dumps(row), flush=True)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    # Check a partially observed limb: JPEG requires a separate lossless Alpha.
    edge = package / 'assets/native_00000_05500/weather_0001.tif'
    edge_hash = hashlib.sha256(edge.read_bytes()).hexdigest()
    assert edge_hash == entries[edge.relative_to(package).as_posix()]['sha256']
    with rasterio.open(edge) as dataset:
        alpha = dataset.read(4)
    mask_path = out / 'limb_alpha.png'
    Image.fromarray(alpha).save(mask_path, compress_level=6)
    assert np.array_equal(np.asarray(Image.open(mask_path)), alpha)
    assert hashlib.sha256(edge.read_bytes()).hexdigest() == edge_hash
    report = dict(scope='two5504x5504 native tiles, night/day UTC; one limb Alpha. Not whole disk/sequence or Blender playback validation.',
                  source_native_pixels_unchanged=True, native_size_derivatives=True,
                  jpeg_replaces_master=False, mask_is_separate=True,
                  limb_alpha_min=int(alpha.min()), limb_alpha_max=int(alpha.max()),
                  limb_alpha_bytes=mask_path.stat().st_size, limb_alpha_exact=True, rows=rows)
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
