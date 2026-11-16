"""ASCII hard-link aliases for Windows NetCDF builds with Unicode path issues."""
import hashlib
import os
from pathlib import Path
import shutil

from .project import check_disk


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reader_paths(root, scene_id, files):
    if os.name != 'nt' or all(str(p).isascii() for p in files):
        return files
    root = Path(root).resolve()
    key = hashlib.sha256(str(root).encode('utf-8')).hexdigest()[:16]
    # NTFS links share bytes. exFAT needs a verified ASCII cache copy instead.
    alias = Path(root.anchor) / 'ges_io_cache' / key / scene_id
    alias.mkdir(parents=True, exist_ok=True)
    result = []
    for source in files:
        target = alias / source.name
        if target.exists():
            if not target.samefile(source) and (target.stat().st_size != source.stat().st_size or digest(target) != digest(source)):
                raise ValueError('Reader alias points to a different archive; preserved')
        else:
            try:
                os.link(source, target)
            except OSError as error:
                if error.winerror not in (1, 50):
                    raise
                check_disk(root, source.stat().st_size)
                temporary = target.with_suffix(target.suffix + '.copying')
                shutil.copy2(source, temporary)
                if digest(temporary) != digest(source):
                    raise ValueError('Reader compatibility copy checksum failed')
                temporary.replace(target)
        result.append(target)
    return result
