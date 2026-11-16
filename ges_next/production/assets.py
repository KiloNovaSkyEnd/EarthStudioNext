"""Small atomic asset/receipt primitives, independent of satellite readers/UI."""
import hashlib
import json
import os
from pathlib import Path
from .atomic_json import write_json


def digest(path):
    from .validation_session import active
    session=active()
    if session is not None:return session.digest(path)
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def record(root, path, role, shape=None):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Asset outside this production package')
    return dict(path=path.relative_to(root).as_posix(), bytes=path.stat().st_size,
                sha256=digest(path), role=role, shape=shape)


def verify_assets(root, entries):
    root = Path(root).resolve()
    seen = set()
    for item in entries:
        name = item['path']
        path = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or name in seen:
            raise ValueError('Unsafe or duplicate asset path')
        seen.add(name)
        path = path.resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Missing asset or escaped package')
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Asset no longer matches committed bytes: ' + name)
    return True
