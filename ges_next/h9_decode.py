"""Independent HSD decompression; compressed L1 originals are never modified."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import bz2
import shutil

def decode_originals(sources,destination,workers=4):
    if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=4:
        raise ValueError('Decode workers must be1 through4')
    destination=Path(destination)
    def decode(source):
        source=Path(source);target=destination/source.name.removesuffix('.bz2')
        if target.exists():raise FileExistsError('Never overwrite an existing decoded source')
        if source.suffix=='.bz2':
            with bz2.open(source,'rb') as inp,target.open('xb') as out:shutil.copyfileobj(inp,out,1024*1024)
        else:shutil.copy2(source,target)
        return target
    with ThreadPoolExecutor(max_workers=workers) as pool:return list(pool.map(decode,sources))
