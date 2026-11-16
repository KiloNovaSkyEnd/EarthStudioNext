"""Bounded read-only compression probes. No satellite downloads/deletes.

Results describe the named regional samples, never a global storage forecast.
Compressed blocks are tested in memory; only a new JSON report is saved.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import zlib
import numpy as np
from numcodecs import Blosc
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def chunks(array, size):
    for y in range(0,array.shape[0],size):
        for x in range(0,array.shape[1],size):
            yield np.ascontiguousarray(array[y:y+size,x:x+size])


def compress(array,size,codec,previous=None):
    total,elapsed,decode_elapsed = 0,0.,0.
    previous_tiles = list(chunks(previous,size)) if previous is not None else None
    equal = 0
    for index,tile in enumerate(chunks(array,size)):
        data=tile.tobytes()
        if previous_tiles is not None:
            before=previous_tiles[index].tobytes()
            equal += data==before
            payload=np.bitwise_xor(np.frombuffer(data,np.uint8),np.frombuffer(before,np.uint8)).tobytes()
        else:
            payload=data
        start=time.perf_counter()
        # Pass typed arrays to Blosc so bitshuffle respects sample width.
        encoded=codec.encode(np.frombuffer(payload,dtype=array.dtype))
        elapsed+=time.perf_counter()-start
        start=time.perf_counter()
        decoded=codec.decode(encoded)
        if previous_tiles is not None:
            decoded=np.bitwise_xor(np.frombuffer(decoded,np.uint8),np.frombuffer(before,np.uint8)).tobytes()
        decode_elapsed+=time.perf_counter()-start
        if decoded!=data:
            raise AssertionError('Decoded bytes differ, including NaN payloads')
        total+=len(encoded)
    return {'encoded_payload_bytes':total,'encode_seconds':elapsed,'decode_seconds':decode_elapsed,
            'bitwise_round_trip':True,'identical_previous_tiles':equal,
            'tile_count':index+1,'tile_edge':size,'includes_container_index_or_checksum_overhead':False}


def main():
    output=Path(sys.argv[1]).resolve()
    if output.exists():
        raise FileExistsError('Choose a new report filename')
    current=ROOT/'data/processed/hinnamnor_geocolor_v1/1130'
    previous=ROOT/'data/processed/hinnamnor_geocolor_v1/1000'
    manifest={}
    def track(path):
        stat=path.stat()
        manifest[str(path.relative_to(ROOT))]={'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        return path
    arrays=np.load(track(current/'observed_inputs.npz'))
    before=np.load(track(previous/'observed_inputs.npz'))
    rgba_path=track(current/'B_current_material_rgba.png')
    before_rgba_path=track(previous/'B_current_material_rgba.png')
    rgba=np.asarray(Image.open(rgba_path)).copy()
    before_rgba=np.asarray(Image.open(before_rgba_path)).copy()
    samples=[('observed B03 reflectance 1km',arrays['B03_fraction_1km'],before['B03_fraction_1km']),
             ('observed B13 brightness temperature 2km',arrays['B13'],before['B13']),
             ('existing derived RGBA material; not raw bands',rgba,before_rgba)]
    results=[]
    codec=Blosc(cname='zstd',clevel=9,shuffle=Blosc.BITSHUFFLE)
    for name,array,prior in samples:
        raw=array.tobytes()
        start=time.perf_counter();baseline=zlib.compress(raw,6)
        baseline_seconds=time.perf_counter()-start
        assert zlib.decompress(baseline)==raw
        entry={'name':name,'shape':list(array.shape),'dtype':str(array.dtype),'uncompressed_bytes':len(raw),
               'deflate_whole_payload_bytes':len(baseline),'deflate_encode_seconds':baseline_seconds,
               'independent_tiles':[], 'temporal_xor_512':None}
        for size in (512,1024):
            entry['independent_tiles'].append(compress(array,size,codec))
        if prior.shape==array.shape and prior.dtype==array.dtype:
            entry['temporal_xor_512']=compress(array,512,codec,prior)
        if array is rgba:
            entry['existing_png_bytes']=rgba_path.stat().st_size
        results.append(entry)
    geographic=[]
    for key in ('longitude_2km','latitude_2km'):
        a,b=arrays[key],before[key]
        geographic.append({'field':key,'bytes_per_frame':a.nbytes,'bitwise_equal_across_pair':a.tobytes()==b.tobytes()})
    for relative,record in manifest.items():
        path=ROOT/relative
        assert path.stat().st_size==record['bytes'] and path.stat().st_mtime_ns==record['mtime_ns']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256']
    report={'scope':'Regional 2022-08-31 10:00 and 11:30 UTC pair, not a global/day forecast',
            'codec':str(codec),'samples':results,'geographic_grid_reuse':geographic,
            'source_files_unchanged':True,'sources':manifest,
            'limits':['Only encoded payload measured; excludes indices, metadata and redundancy',
                      'Temporal pair is 90 minutes apart, not a 10 minute sequence',
                      'Float arrays already decoded/calibrated; no claim of original raw-container byte preservation',
                      'Existing 8-bit RGBA sample is not a proposed full-precision master specification']}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps([{'sample':r['name'],'raw_MB':round(r['uncompressed_bytes']/1e6,3),
        'deflate_MB':round(r['deflate_whole_payload_bytes']/1e6,3),
        'zstd_512_MB':round(r['independent_tiles'][0]['encoded_payload_bytes']/1e6,3),
        'xor_512_MB':round(r['temporal_xor_512']['encoded_payload_bytes']/1e6,3),
        'png_MB':round(r.get('existing_png_bytes',0)/1e6,3)} for r in results],ensure_ascii=False))


if __name__=='__main__':
    main()
