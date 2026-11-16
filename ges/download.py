"""NOAA anonymous S3 download: byte-verified cache and atomic file writes.

Temporary .part downloads are discarded after failures; range resume is not yet implemented.
"""
from pathlib import Path
import json
import os
from .catalog import Scene, scene_as_json
from .storage import StorageConfig, preflight, default_config


def cached_bytes(scene: Scene, dest: Path) -> int:
    count = 0
    for i, key in enumerate(scene.keys):
        expected = scene.object_sizes[i] if i < len(scene.object_sizes) else None
        path = dest / Path(key).name
        if expected is not None and path.is_file() and path.stat().st_size == expected:
            count += expected
    return count


def download_scene(s3, scene: Scene, root: Path, config: StorageConfig | None = None) -> Path:
    cfg = config or default_config()
    dest = root / scene.scene_id
    # No mkdir before disk preflight: reserve check must assess actual volume.
    preflight(scene.total_bytes, dest, cfg, existing_bytes=cached_bytes(scene, dest))
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for idx, key in enumerate(scene.keys):
        expected = scene.object_sizes[idx] if idx < len(scene.object_sizes) else None
        target = dest / Path(key).name
        if not (target.is_file() and expected is not None and target.stat().st_size == expected):
            partial = target.with_suffix(target.suffix + '.part')
            partial.unlink(missing_ok=True)
            try:
                s3.download_file(scene.bucket, key, str(partial))
                if expected is not None and partial.stat().st_size != expected:
                    raise IOError(f'下载字节数与目录不一致: {target.name}: expected={expected}, actual={partial.stat().st_size}')
                if partial.stat().st_size == 0:
                    raise IOError(f'下载为空文件: {target.name}')
                os.replace(partial, target)
            finally:
                partial.unlink(missing_ok=True)
        files.append(str(target.resolve()))
    manifest = scene_as_json(scene)
    manifest['local_files'] = files
    manifest['notes'] = ('Original NOAA AWS satellite objects. Size-verified, not yet checksum-verified. '
                         'No synthetic cloud pixels.')
    p = dest / 'scene.json'
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, p)
    return p


def read_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    missing = [p for p in data['local_files'] if not Path(p).is_file()]
    if missing:
        raise FileNotFoundError('文件丢失：' + '; '.join(missing[:3]))
    sizes = data.get('object_sizes',[])
    for i, file in enumerate(data['local_files']):
        if i < len(sizes) and sizes[i] != Path(file).stat().st_size:
            raise IOError(f'文件大小不匹配（缓存可能损坏）: {file}')
    return data
