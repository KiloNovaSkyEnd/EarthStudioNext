"""Bounded real native tile chunk/worker controls; never enables a candidate."""
import argparse
from contextlib import nullcontext
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges.earth_validation import stock,resources
from ges.earth_validation.spill import bounded_compute
from ges.earth_validation.project import save
from ges_next.h9_decode import decode_originals
from ges_next.isolation import require_writable
from scripts.benchmark_h9_static_io import TaskTiming
import numpy as np
import rasterio
import satpy
from satpy import Scene
import yaml


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--utc',default='20261020T1500Z')
    parser.add_argument('--source-directory',type=Path,help='Existing read-only compressed scan, never downloaded')
    parser.add_argument('--baseline',type=Path,help='Previously qualified same-UTC native tile')
    parser.add_argument('--runs',default='512x6,1024x6,2048x4,1024x4,1024x6,512x6')
    parser.add_argument('--gdal-thread-runs',help='Per-run lossless encoder threads,4 or8; research only')
    parser.add_argument('--decoded-directory',type=Path,help='Reuse existing read-only decoded inputs after committed SHA verification')
    parser.add_argument('--discard-candidate-tiffs',action='store_true',help='Keep metrics only after parity validation')
    args=parser.parse_args();p=args.project.resolve();out=require_writable(args.output)
    out.mkdir(parents=True,exist_ok=False)
    if shutil.disk_usage(out).free<28*1024**3:raise RuntimeError('Insufficient bounded experiment storage')
    source_dir=args.source_directory or p/'raw'/args.utc
    sources=sorted(path for path in source_dir.glob('*.DAT.bz2')
        if any('_'+band+'_' in path.name for band in ['B01','B02','B03','B04','B07','B13']))
    if len(sources)!=60:raise ValueError('Requires retained complete scan; no downloads')
    def digest(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    source_hashes={str(path):digest(path) for path in sources}
    save(out/'project.json',dict(compute_workers=6,reserve_free_bytes=16*1024**3))
    reference=ROOT.parent/'GlobalSatelliteEarthStudio/data/raw/reference'
    stock.configure(out)
    config=out/'scratch/pyspectral_runtime.yaml'
    config.write_text(yaml.safe_dump(dict(download_from_internet=False,
        rayleigh_dir=str(reference/'pyspectral'),rsr_dir=str(reference/'pyspectral/rsr'))))
    os.environ['PSP_CONFIG_FILE']=str(config)
    os.environ['EARTHSTUDIO_H9_CUDA_CLOUDS']='2'
    satpy.config.set(data_dir=str(reference/'satpy_geocolor_v060'),download_aux=False,
        config_path=[str(ROOT/'ges/earth_validation/satpy_config'),str(ROOT/'ges/earth_validation/cuda_satpy_config')],
        cache_lonlats=False,cache_sensor_angles=False)
    with rasterio.open(args.baseline or p/'processed'/args.utc/'native_05500_05500.tif') as src:
        baseline=(src.read(),src.transform,src.crs)
    records=[]
    decoded_context=nullcontext(str(args.decoded_directory.resolve())) if args.decoded_directory else tempfile.TemporaryDirectory(prefix='private_decoded_',dir=out,ignore_cleanup_errors=True)
    with decoded_context as temp:
        decoded=Path(temp).resolve()
        if args.decoded_directory:
            stamp=args.utc
            inventory=json.loads((p/'processed'/stamp/'input_inventory.json').read_text())
            expected={Path(f['path']).name:f for f in inventory['files']}
            files=sorted(decoded.glob('*.DAT'))
            if len(files)!=60 or {f.name for f in files}!=set(expected):raise ValueError('Reused decoded scan inventory differs')
            if any(digest(f)!=expected[f.name]['sha256'] for f in files):raise ValueError('Reused decoded bytes differ from committed scan')
        else:
            if not decoded.is_relative_to(out):raise ValueError('Decoded experiment path outside its root')
            files=decode_originals(sources,decoded,workers=4)
        labels=args.runs.split(',')
        encoders=list(map(int,args.gdal_thread_runs.split(','))) if args.gdal_thread_runs else [4]*len(labels)
        if len(encoders)!=len(labels) or any(v not in (4,8) for v in encoders):raise ValueError('Encoder controls must match runs and use4 or8 threads')
        for index,label in enumerate(labels):
            shared=label.endswith('s')
            chunk,workers=map(int,label.removesuffix('s').split('x'));stock.validate_compute_chunk(chunk)
            if workers not in (4,6,8):raise ValueError('Only bounded worker controls accepted')
            paths=[str(ROOT/'ges/earth_validation/satpy_config'),str(ROOT/'ges/earth_validation/cuda_satpy_config')]
            if shared:paths.append(str(ROOT/'ges/earth_validation/solar_satpy_config'))
            satpy.config.set(config_path=paths)
            from ges.earth_validation.solar_shared import factor_sample
            factors_before=factor_sample.copy()
            start=time.perf_counter();scene=Scene(reader='ahi_hsd',filenames=[str(f) for f in files])
            scene.load(['B01','B02','B03','B04','B07','B13'])
            target=scene['B03'].attrs['area'][5500:11000,5500:11000]
            result,area=stock.compose(scene,target,p/'raw/references/blackmarble_2016_500m/global_500m.vrt',
                reference,native=True,native_tile=True,night_cache=p/'shared_static/night_grids',
                night_io='mmap',compute_chunk=chunk)
            planned=time.perf_counter();path=out/f'{index}_{label}.tif';timing=TaskTiming()
            before=resources.gpu_sample.copy()
            with bounded_compute(out,workers=workers) as cache,timing:
                admitted_workers=resources.spill_sample.get('admitted_workers')
                if admitted_workers!=workers:
                    save(out/'deferred.json',dict(reason='Insufficient headroom for a valid worker comparison',
                        requested_workers=workers,admitted_workers=admitted_workers,
                        physical_available_bytes=resources.psutil.virtual_memory().available,
                        commit=resources.commit_usage(),candidate_activated=False))
                    raise RuntimeError('Benchmark deferred: actual worker admission differs from requested; preserve production headroom')
                result.save_dataset('geo_color',filename=str(path),writer='geotiff',dtype=np.uint8,
                    compress='DEFLATE',tiled=True,blockxsize=256,blockysize=256,predictor=2,
                    zlevel=6,num_threads=encoders[index],include_scale_offset_tags=False)
                spilled=cache.written_bytes
                admitted_workers=resources.spill_sample.get('admitted_workers')
            ended=time.perf_counter()
            with rasterio.open(path) as src:actual=(src.read(),src.transform,src.crs)
            equal=np.array_equal(actual[0],baseline[0]) and actual[1:]==baseline[1:]
            difference=np.abs(actual[0].astype(np.int16)-baseline[0].astype(np.int16))
            record=dict(label=label,compute_chunk=chunk,workers=workers,admitted_workers=admitted_workers,planning_open_seconds=planned-start,
                gdal_threads=encoders[index],output_bytes=path.stat().st_size,
                process_peak_rss_bytes=getattr(resources.psutil.Process().memory_info(),'peak_wset',None),
                shared_solar_factors=shared,
                solar_factor_execution={k:v-factors_before.get(k,0) for k,v in factor_sample.items()},
                compute_write_seconds=ended-planned,inclusive_seconds=ended-start,
                exact_rgba_grid_equal_to_committed=equal,max_byte_difference=int(difference.max()),
                differing_channel_values=int(np.count_nonzero(difference)),graph_tasks=timing.graph_tasks,
                spilled_bytes=spilled,gpu_calls=resources.gpu_sample.get('calls',0)-before.get('calls',0),
                gpu_pixels=resources.gpu_sample.get('pixels',0)-before.get('pixels',0),
                task_groups=sorted([dict(prefix=k,count=v[0],summed_task_seconds=v[1])
                    for k,v in timing.groups.items()],key=lambda x:-x['summed_task_seconds'])[:16])
            records.append(record)
            save(out/'results.json',dict(utc=args.utc,shape=list(actual[0].shape),records=records,
                limits='Same retained native tile, exact committed-pixel reference; active production competes. '
                'Chunk size affects execution only; candidate not activated by this benchmark.'))
            print(json.dumps({k:v for k,v in record.items() if k!='task_groups'}),flush=True)
            del result,scene,actual,difference;gc.collect()
            if args.discard_candidate_tiffs:path.unlink()
        if any(digest(Path(path))!=sha for path,sha in source_hashes.items()):
            raise ValueError('Original compressed input changed during benchmark')
        save(out/'source_integrity.json',dict(compressed_inputs_unchanged=True,sha256=source_hashes))
        if args.decoded_directory and any(digest(f)!=expected[f.name]['sha256'] for f in files):
            raise ValueError('Read-only decoded inputs changed during experiment')


if __name__=='__main__':main()
