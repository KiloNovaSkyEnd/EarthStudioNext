"""Bounded parallel BZ2 expansion; byte-exact HSD files, no image resampling."""
import bz2
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from .project import save,check_disk


def expand(paths,root,scene_id):
    folder=Path(root)/'processed/hsd_reader_cache'/scene_id
    folder.mkdir(parents=True,exist_ok=True)
    result=[]; pending=[]
    for source in paths:
        source=Path(source); target=folder/source.stem
        receipt=target.with_suffix(target.suffix+'.json')
        identity={'size':source.stat().st_size,'mtime_ns':source.stat().st_mtime_ns}
        if receipt.is_file() and target.is_file():
            record=json.loads(receipt.read_text(encoding='utf-8'))
            stamp={'size':target.stat().st_size,'mtime_ns':target.stat().st_mtime_ns}
            if record['source_stamp']==identity and record['cache_stamp']==stamp:
                result.append(target); continue
            raise ValueError('HSD reader cache changed; preserved for inspection')
        result.append(target); pending.append((source,target,receipt,identity))
    if not pending: return result
    # Peak buffers stay below ~1GB; writes are committed in source order to
    # avoid multiple concurrent large writes thrashing an archive HDD.
    check_disk(root,len(pending)*100_000_000)
    def decode(item):
        compressed=item[0].read_bytes(); values=bz2.decompress(compressed)
        return values,hashlib.sha256(compressed).hexdigest(),hashlib.sha256(values).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool:
        waiting=deque(); iterator=iter(pending)
        for _ in range(min(4,len(pending))):
            item=next(iterator); waiting.append((item,pool.submit(decode,item)))
        while waiting:
            item,future=waiting.popleft(); values,source_sha,cache_sha=future.result()
            source,target,receipt,identity=item
            temporary=target.with_suffix(target.suffix+'.part')
            temporary.write_bytes(values); del values
            temporary.replace(target)
            save(receipt,{'source':str(source),'source_stamp':identity,'source_sha256':source_sha,
                'cache_stamp':{'size':target.stat().st_size,'mtime_ns':target.stat().st_mtime_ns},
                'cache_sha256':cache_sha,'operation':'Lossless BZ2 decompression only'})
            print('HSD_CACHE',scene_id,target.name,flush=True)
            item=next(iterator,None)
            if item is not None: waiting.append((item,pool.submit(decode,item)))
    return result
