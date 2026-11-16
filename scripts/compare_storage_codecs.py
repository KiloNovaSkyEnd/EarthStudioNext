"""Fair per-tile follow-up to the bounded storage probe; no archive mutations."""
import json
from pathlib import Path
import sys
import zlib
import numpy as np
from numcodecs import Blosc
from PIL import Image
from analyze_storage_lossless import compress, ROOT


class Deflate:
    def encode(self,array):
        return zlib.compress(array.tobytes(),6)
    def decode(self,data):
        return zlib.decompress(data)


output=Path(sys.argv[1]).resolve()
if output.exists():
    raise FileExistsError(output)
folder=ROOT/'data/processed/hinnamnor_geocolor_v1/1130'
arrays=np.load(folder/'observed_inputs.npz')
samples=[('B03 1km float32',arrays['B03_fraction_1km']),('B13 2km float32',arrays['B13']),
         ('derived RGBA8',np.asarray(Image.open(folder/'B_current_material_rgba.png')).copy())]
codecs=[('DEFLATE6',Deflate()),('ZSTD5_no_shuffle',Blosc(cname='zstd',clevel=5,shuffle=0)),
        ('ZSTD5_byte_shuffle',Blosc(cname='zstd',clevel=5,shuffle=1))]
records=[]
for name,array in samples:
    for label,codec in codecs:
        print(name,label,flush=True)
        record=compress(array,512,codec)
        record.update(sample=name,codec=label)
        records.append(record)
output.write_text(json.dumps({'records':records,'scope':'Same regional samples; 512x512 tiles; byte-exact codec probes only'},indent=2),encoding='utf-8')
print(json.dumps([{k:r[k] for k in ('sample','codec','encoded_payload_bytes')} for r in records]))
