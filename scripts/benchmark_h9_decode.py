"""Four actual HSD compressed originals, serial vs4-thread decode and exact SHA."""
from pathlib import Path
import sys,json,time,tempfile,hashlib
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from ges_next.h9_decode import decode_originals
p=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
sources=sorted((p/'raw/20261020T1430Z').glob('*.DAT.bz2'),key=lambda f:f.stat().st_size,reverse=True)[:4]
if len(sources)!=4:raise ValueError('Four actual retained H9 sources required')
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
before=[sha(f) for f in sources];records=[];expected=None
for workers in [1,4]:
    with tempfile.TemporaryDirectory(prefix='decode_qualification_',dir=p/'scratch') as temp:
        began=time.monotonic();files=decode_originals(sources,Path(temp),workers=workers);elapsed=time.monotonic()-began
        hashes=[sha(f) for f in files]
        if expected is None:expected=hashes
        assert expected==hashes
        records.append(dict(workers=workers,seconds=elapsed,decoded_sha256=hashes))
        print('DECODE_BENCH',json.dumps(records[-1]),flush=True)
assert before==[sha(f) for f in sources]
(p/'reports/decode_parallel_qualification.json').write_text(json.dumps(dict(source_files=[str(f) for f in sources],records=records,
    identical_decoded_bytes=True,compressed_originals_unchanged=True),indent=2),encoding='utf-8')
