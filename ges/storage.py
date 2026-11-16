"""Non-destructive local paths and disk-budget checks for satellite archives.

No background cleanup: user-created and downloaded scientific files are never deleted.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import os
import shutil

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / 'local_storage.json'

@dataclass(frozen=True)
class StorageConfig:
    raw_dir: Path
    processed_dir: Path
    export_dir: Path
    max_single_scene_gb: float = 5.0
    reserve_free_gb: float = 10.0

    def validate(self) -> None:
        for label, path in [('raw_dir', self.raw_dir), ('processed_dir', self.processed_dir),
                            ('export_dir', self.export_dir)]:
            if not str(path).strip():
                raise ValueError(f'{label} is empty')
        roots = [p.expanduser().resolve() for p in (self.raw_dir, self.processed_dir, self.export_dir)]
        for i, left in enumerate(roots):
            for right in roots[i+1:]:
                if left == right or left in right.parents or right in left.parents:
                    raise ValueError('Raw / processed / export roots must be separate (non-nested) directories')
        if not (0.1 <= self.max_single_scene_gb <= 100.0):
            raise ValueError('max_single_scene_gb must be between 0.1 and 100')
        if not (0 <= self.reserve_free_gb <= 500):
            raise ValueError('reserve_free_gb must be between 0 and 500')


def default_config() -> StorageConfig:
    return StorageConfig(ROOT/'data'/'raw', ROOT/'data'/'processed', ROOT/'data'/'exports')


def load_config(path: Path = CONFIG_PATH) -> StorageConfig:
    baseline = default_config()
    if not path.exists():
        return baseline
    obj = json.loads(path.read_text(encoding='utf-8'))
    cfg = StorageConfig(
        raw_dir=Path(obj.get('raw_dir', str(baseline.raw_dir))),
        processed_dir=Path(obj.get('processed_dir', str(baseline.processed_dir))),
        export_dir=Path(obj.get('export_dir', str(baseline.export_dir))),
        max_single_scene_gb=float(obj.get('max_single_scene_gb',baseline.max_single_scene_gb)),
        reserve_free_gb=float(obj.get('reserve_free_gb',baseline.reserve_free_gb)))
    cfg.validate()
    return cfg


def save_config(cfg: StorageConfig, path: Path = CONFIG_PATH) -> None:
    cfg.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {'raw_dir':str(cfg.raw_dir.expanduser().resolve()),
            'processed_dir':str(cfg.processed_dir.expanduser().resolve()),
            'export_dir':str(cfg.export_dir.expanduser().resolve()),
            'max_single_scene_gb':cfg.max_single_scene_gb,
            'reserve_free_gb':cfg.reserve_free_gb}
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp,path)


def _nearest_existing(path: Path) -> Path:
    parent = path.expanduser().resolve()
    while not parent.exists():
        if parent == parent.parent:
            raise ValueError(f'Cannot determine volume for {path}')
        parent = parent.parent
    return parent


def preflight(scene_total_bytes: int, out_dir: Path, cfg: StorageConfig,
              existing_bytes: int = 0, disk_usage=None) -> dict[str, Any]:
    """Validate expected remaining scene download vs caps and free disk.

    existing_bytes is verified scene data already cached, not arbitrary other files.
    """
    cfg.validate()
    if scene_total_bytes < 0 or existing_bytes < 0 or existing_bytes > scene_total_bytes:
        raise ValueError('Invalid remote/cache byte counts')
    if scene_total_bytes > cfg.max_single_scene_gb * 1e9:
        raise RuntimeError(f'场景总量 {scene_total_bytes/1e9:.2f} GB 超过单次预算 '
                           f'{cfg.max_single_scene_gb:.2f} GB；修改本地存储设置后再下载。')
    remaining = scene_total_bytes-existing_bytes
    disk = (disk_usage or shutil.disk_usage)(_nearest_existing(out_dir))
    free_after = disk.free-remaining
    if free_after < cfg.reserve_free_gb*1e9:
        raise RuntimeError(f'磁盘空间不足：尚需 {remaining/1e9:.2f} GB，下载后预计剩余 '
                           f'{free_after/1e9:.2f} GB，须保留 {cfg.reserve_free_gb:.2f} GB。')
    return {'scene_gb': round(scene_total_bytes/1e9,3),
            'remaining_gb': round(remaining/1e9,3),
            'free_after_gb':round(free_after/1e9,3)}
