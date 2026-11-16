"""Read-only historical H9 input adapter with job-owned atomic decode cache."""
import bz2
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
from .assets import digest, write_json


def decode(sources, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    def one(source):
        target = destination/source.name.removesuffix('.bz2')
        receipt = target.with_suffix('.decode.json')
        identity = dict(source=str(source.resolve()), bytes=source.stat().st_size, sha256=digest(source))
        if target.exists():
            import json
            if not receipt.exists(): raise ValueError('Decoded cache without receipt; preserved')
            old = json.loads(receipt.read_text(encoding='utf-8'))
            if old['input'] != identity or old['decoded_sha256'] != digest(target): raise ValueError('Decoded cache differs')
            return target, identity
        part = target.with_suffix('.DAT.part')
        # Only this job-owned uncommitted decode cache may be retried.
        with bz2.open(source, 'rb') as inp, part.open('wb') as out:
            shutil.copyfileobj(inp, out, 1024*1024)
        write_json(receipt, dict(input=identity, decoded_sha256=digest(part)))
        part.replace(target)
        return target, identity
    from ges_next.performance.policy import settings
    with ThreadPoolExecutor(max_workers=settings()['decode_workers']) as pool:
        values = list(pool.map(one, sources))
    return [v[0] for v in values], [v[1] for v in values]


def source_files(root, utc, paths=None,bands=None):
    from datetime import datetime
    import re
    stamp = datetime.fromisoformat(utc.replace('Z','+00:00'))
    from datetime import timedelta
    if stamp.utcoffset()!=timedelta(0) or stamp.second or stamp.microsecond or stamp.minute%10:
        raise ValueError('Exact UTC ten-minute scan time required')
    folder = Path(root)/'raw'/stamp.strftime('%Y%m%dT%H%MZ')
    files = sorted(folder.glob('HS_H09_*.DAT.bz2')) if paths is None else sorted(map(Path,paths))
    bands=bands or ['B01','B02','B03','B04','B07','B13']
    expected = {(b,s) for b in bands for s in range(1,11)}
    found = []
    for file in files:
        match = re.fullmatch(rf'HS_H09_{stamp:%Y%m%d_%H%M}_(B\d\d)_FLDK_R\d\d_S(\d\d)10\.DAT\.bz2', file.name)
        if not match: raise ValueError('Input scan identity differs')
        found.append((match[1],int(match[2])))
    if len(files) != len(expected) or set(found) != expected: raise ValueError('Complete selected-band ten-segment scan required')
    return files
