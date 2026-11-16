"""Explicit export of a processed product and provenance. Never overwrite exports."""
from __future__ import annotations
from pathlib import Path
import shutil


def export_product(source: Path, export_dir: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() != '.png':
        raise ValueError('Currently only processed PNG can be exported')
    export_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    while True:
        stem = source.stem if n == 0 else f'{source.stem}_{n:03d}'
        target = export_dir / (stem + '.png')
        try:
            with target.open('xb') as dst, source.open('rb') as src:
                shutil.copyfileobj(src, dst)
            break
        except FileExistsError:
            n += 1
    meta = source.with_suffix('.json')
    if meta.is_file():
        shutil.copyfile(meta, target.with_suffix('.json'))
    return target
