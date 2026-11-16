"""Actual native crop CPU/CUDA/CPU GeoColor parity and inclusive timings."""
from pathlib import Path
from datetime import datetime
import os,sys,json,time,gc,argparse,shutil,tempfile
import numpy as np
import rasterio,yaml,satpy
from satpy import Scene
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from ges.earth_validation import stock
from ges.earth_validation.spill import bounded_compute
from ges.earth_validation.project import save
from ges.earth_validation import resources

p=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--size',type=int,choices=[1536,5500],default=1536)
parser.add_argument('--runs',default='cpu,cuda,cuda,cpu')
parser.add_argument('--output',type=Path,default=p/'reports/cuda_geocolor_benchmark')
parser.add_argument('--utc',default=None)
parser.add_argument('--raw',type=Path,default=None)
options=parser.parse_args()
out=options.output.resolve()
from ges_next.isolation import require_writable
require_writable(out);out.mkdir(exist_ok=False)
status=json.loads((p/'reports/status.json').read_text())
if options.utc:status['utc']=options.utc
stamp=datetime.fromisoformat(status['utc'].replace('Z','+00:00'))
decoded=[options.raw] if options.raw else list((p/'scratch').glob(f'decoded_{stamp:%H%M}_*'))
if len(decoded)!=1:raise ValueError('Requires active decoded observation')
files=sorted(decoded[0].glob(f'HS_H09_{stamp:%Y%m%d_%H%M}_*.DAT'))
if len(files)!=60:raise ValueError('Exact60 originals required')
private_sources=tempfile.TemporaryDirectory(prefix='decoded_native_benchmark_',dir=out,ignore_cleanup_errors=True)
for source in files:shutil.copy2(source,Path(private_sources.name)/source.name)
files=sorted(Path(private_sources.name).glob('*.DAT'))
reference=root.parent/'GlobalSatelliteEarthStudio/data/raw/reference'
save(out/'project.json',dict(reserve_free_bytes=16*1024**3,compute_workers=6))
stock.configure(out)
config=out/'scratch/pyspectral_runtime.yaml'
config.write_text(yaml.safe_dump(dict(download_from_internet=False,rayleigh_dir=str(reference/'pyspectral'),rsr_dir=str(reference/'pyspectral/rsr'))))
os.environ['PSP_CONFIG_FILE']=str(config)
satpy.config.set(data_dir=str(reference/'satpy_geocolor_v060'),download_aux=False)
records=[];baseline=None
for index,backend in enumerate(options.runs.split(',')):
    os.environ['EARTHSTUDIO_H9_CUDA_CLOUDS']='2' if backend=='cuda_night' else '1' if backend=='cuda' else '0'
    paths=[str(root/'ges/earth_validation/satpy_config')]
    if backend=='cuda_night':paths.append(str(root/'ges/earth_validation/cuda_satpy_config'))
    satpy.config.set(config_path=paths)
    scene=Scene(reader='ahi_hsd',filenames=[str(f) for f in files]);scene.load(['B01','B02','B03','B04','B07','B13'])
    target=scene['B03'].attrs['area'][5500:11000,5500:11000] if options.size==5500 else scene['B03'].attrs['area'][6500:8036,10000:11536]
    start=time.monotonic()
    result,area=stock.compose(scene,target,p/'raw/references/blackmarble_2016_500m/global_500m.vrt',reference,
        native=True,native_tile=True,night_cache=p/'shared_static/night_grids')
    graph=time.monotonic()-start;path=out/f'{index}_{backend}.tif'
    before=resources.gpu_sample.get('calls',0)
    with bounded_compute(out,workers=6):
        result.save_dataset('geo_color',filename=str(path),writer='geotiff',dtype=np.uint8,compress='DEFLATE',
            tiled=True,blockxsize=256,blockysize=256,predictor=2,zlevel=6,num_threads=4,include_scale_offset_tags=False)
    elapsed=time.monotonic()-start
    with rasterio.open(path) as src:actual=(src.read(),src.transform,src.crs)
    if baseline is None:baseline=actual
    equal=np.array_equal(actual[0],baseline[0]) and actual[1:]==baseline[1:]
    record=dict(backend=backend,graph_seconds=graph,inclusive_seconds=elapsed,
        identical_final_rgba_and_georeferencing=equal,max_byte_difference=int(np.abs(actual[0].astype(int)-baseline[0]).max()),
        gpu_calls=resources.gpu_sample.get('calls',0)-before,gpu_telemetry=resources.gpu_sample.copy())
    records.append(record)
    save(out/'results.json',dict(utc=status['utc'],shape=list(actual[0].shape),records=records,
        limits='One original native crop; includes graph construction, transfers, scientific kernels, encoding. Production active. Full frame unverified.'))
    print('CUDA_GEOCOLOR',json.dumps(record),flush=True)
    if not equal:raise ValueError('FinalRGBA parity failed; production CUDA must stay disabled')
    if backend.startswith('cuda') and record['gpu_calls']==0:raise ValueError('No scientific CUDA calls actually executed')
    del result,scene;gc.collect()
if private_sources:private_sources.cleanup()
