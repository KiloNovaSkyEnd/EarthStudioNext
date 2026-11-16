"""One full native scan: unchanged observations/recipe, experimental mmap I/O."""
import argparse
from contextlib import nullcontext
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges_next.isolation import require_writable
from ges_next.h9_decode import decode_originals


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--utc',default='2026-10-20T15:00:00Z')
    parser.add_argument('--compute-chunk',type=int,choices=[512,1024,2048],default=512)
    parser.add_argument('--shared-solar',action='store_true')
    parser.add_argument('--gdal-threads',type=int,choices=[4,8])
    parser.add_argument('--decoded-directory',type=Path)
    parser.add_argument('--parallel-rows',type=int,choices=[1,2],help='Bound the extra qualification load independently of production')
    args=parser.parse_args()
    p=args.project.resolve();out=require_writable(args.output);out.mkdir(parents=True,exist_ok=False)
    if shutil.disk_usage(out).free<28*1024**3:raise RuntimeError('Full native experiment needs bounded storage reserve')
    stamp=datetime.fromisoformat(args.utc.replace('Z','+00:00'))
    sources=sorted((p/'raw'/stamp.strftime('%Y%m%dT%H%MZ')).glob('*.DAT.bz2'))
    if len(sources)!=60:raise ValueError('Requires complete retained scan, no downloads')
    for source in sources:
        receipt=json.loads(source.with_suffix(source.suffix+'.json').read_text(encoding='utf-8'))
        if digest(source)!=receipt['sha256']:raise ValueError('Retained L1 checksum differs')
    profile=json.loads((p/'compute_profile.json').read_text(encoding='utf-8'))
    profile.update(night_io='mmap',night_io_pixel_parity_qualified=True,
        night_io_qualification='Prior eight full native tile RGBA/grid comparisons; experimental full-scan validation underway')
    profile.update(compute_chunk=args.compute_chunk,compute_chunk_pixel_parity_qualified=True,
        shared_solar_factors=args.shared_solar,solar_factors_pixel_parity_qualified=True)
    if args.parallel_rows is not None:profile['parallel_rows']=args.parallel_rows
    if args.gdal_threads is not None:
        profile.update(gdal_threads=args.gdal_threads,encoding_threads8_pixel_parity_qualified=True)
    profile_path=out/'experimental_profile.json';profile_path.write_text(json.dumps(profile,indent=2))
    scope=json.loads((p/'requested_scope.json').read_text(encoding='utf-8'))
    began=time.monotonic()
    context=nullcontext(str(args.decoded_directory.resolve())) if args.decoded_directory else tempfile.TemporaryDirectory(prefix='private_decoded_',dir=out,ignore_cleanup_errors=True)
    with context as temp:
        if args.decoded_directory:
            inventory=json.loads((p/'processed'/stamp.strftime('%Y%m%dT%H%MZ')/'input_inventory.json').read_text())
            expected={Path(f['path']).name:f['sha256'] for f in inventory['files']}
            reused=sorted(Path(temp).glob('*.DAT'))
            if len(reused)!=60 or {f.name for f in reused}!=set(expected):raise ValueError('Decoded inventory differs')
            if any(digest(f)!=expected[f.name] for f in reused):raise ValueError('Decoded bytes differ')
        else:decode_originals(sources,Path(temp),workers=4)
        command=[sys.executable,'-X','utf8','-u',str(ROOT/'scripts/prepare_native_h9_disk.py'),
            '--utc',args.utc,'--raw',str(temp),'--reference',str(ROOT.parent/'GlobalSatelliteEarthStudio/data/raw/reference'),
            '--night',str(p/'raw/references/blackmarble_2016_500m/global_500m.vrt'),
            '--output',str(out/'native'),'--shared-static-cache',str(p/'shared_static'),
            '--scope-generation',str(scope['generation']),'--performance-profile',str(profile_path)]
        with (out/'native.log').open('w',encoding='utf-8') as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    native=out/'native'
    candidate=json.loads((native/'native_master.json').read_text(encoding='utf-8'))
    reference=p/'processed'/stamp.strftime('%Y%m%dT%H%MZ')
    baseline=json.loads((reference/'native_master.json').read_text(encoding='utf-8'))
    if candidate['utc']!=baseline['utc'] or candidate['shape']!=baseline['shape']:
        raise ValueError('Scan identity/grid changed')
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    comparisons=[]
    for tile in candidate['tiles']:
        with rasterio.open(reference/tile['path']) as a,rasterio.open(native/tile['path']) as b:
            equal=a.shape==b.shape and a.transform==b.transform and a.crs==b.crs and a.count==b.count==4
            for row in range(0,a.height,256):
                window=Window(0,row,a.width,min(256,a.height-row))
                equal=equal and np.array_equal(a.read(window=window),b.read(window=window))
        if not equal:raise ValueError('Native pixel/grid parity failed: '+tile['path'])
        if tile['execution']['night_io']!='mmap':raise ValueError('Requested I/O did not execute')
        if tile['execution'].get('compute_chunk',512)!=args.compute_chunk:
            raise ValueError('Requested chunk did not execute')
        if args.shared_solar and not tile['execution'].get('solar_factor_execution',{}).get('cos_calls',0):
            raise ValueError('Shared solar factors did not execute')
        if args.gdal_threads is not None and tile['execution'].get('gdal_threads')!=args.gdal_threads:
            raise ValueError('Requested encoder threads did not execute')
        comparisons.append(dict(tile=tile['path'],all_rgba_and_grid_exact=True,
            execution=tile['execution'],bytes=(native/tile['path']).stat().st_size,sha256=digest(native/tile['path'])))
    if len(comparisons)!=16:raise ValueError('Incomplete native scan')
    for source in sources:
        receipt=json.loads(source.with_suffix(source.suffix+'.json').read_text(encoding='utf-8'))
        if digest(source)!=receipt['sha256']:raise ValueError('L1 changed during experiment')
    if args.decoded_directory and any(digest(f)!=expected[f.name] for f in reused):raise ValueError('Decoded bytes changed')
    report=dict(qualified=True,created_utc=datetime.now(timezone.utc).isoformat(),utc=args.utc,
        native_shape=candidate['shape'],all_16_native_tiles_exact=True,source_compressed_l1_unchanged=True,
        compute_chunk=args.compute_chunk,shared_solar_factors=args.shared_solar,
        parallel_rows=profile.get('parallel_rows',1),
        gdal_threads=profile.get('gdal_threads',1),
        experimental_native_seconds=candidate['runSeconds'],total_qualification_seconds=time.monotonic()-began,
        comparisons=comparisons,limits='Full scan exact quality qualification. Active production competes; '
        'baseline production timing used a different backend/runtime and is not a controlled mmap speed ratio.')
    (out/'results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='comparisons'}),flush=True)


if __name__=='__main__':main()
