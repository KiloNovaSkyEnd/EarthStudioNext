"""Stock Satpy recipes with a single substituted, georeferenced night input.

Both proxy and native-grid tiles call this module. No legacy material imports.
"""
import gc
import json
import os
from . import bootstrap  # noqa: F401; before Satpy / pyresample
from time import perf_counter
from pathlib import Path
import dask
import dask.array as da
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
import satpy
from satpy import Scene
import xarray as xr
import yaml
from .archive import target_for, sha
from .io_paths import reader_paths
from .native import RECIPES
from .night_background import read_on_area
from .project import save, check_disk,observation_interval
from .compute_progress import ComputeProgress
from .arrays import ReadOnlyArray
from .coverage import observed_support, SUPPORT_VERSION

PROFILE = 'satpy-stock-geocolor-soft-rim-v1'
SUPPORTED = {'himawari8','goes16','goes17','meteosat_zero','meteosat_iodc'}
SEVIRI_BANDS = ['VIS006','VIS008','IR_016','IR_039','IR_108']

class EmptyObservation(ValueError):
    """The requested footprint has no valid same-scan source support."""


def composite_name(sensor):
    return 'observed_natural_day_night' if sensor.startswith('meteosat') else 'geo_color'


def configure(root):
    if satpy.__version__ != '0.60.0':
        raise RuntimeError('Equivalent low-cloud execution is qualified for Satpy 0.60.0 only')
    reference = Path(__file__).resolve().parents[2]/'data/raw/reference'
    spectral_config=Path(root)/'scratch/pyspectral_runtime.yaml'
    spectral_config.parent.mkdir(parents=True,exist_ok=True)
    spectral_config.write_text(yaml.safe_dump({'download_from_internet':False,
        'rayleigh_dir':str(reference/'pyspectral'),'rsr_dir':str(reference/'pyspectral/rsr')}),encoding='utf-8')
    os.environ['PSP_CONFIG_FILE'] = str(spectral_config)
    os.environ['OMP_NUM_THREADS'] = '2'
    # Avoid GDAL's default fraction-of-system-RAM cache competing with Dask.
    os.environ['GDAL_CACHEMAX'] = '256'
    os.environ['PYTROLL_CHUNK_SIZE'] = '512'
    satpy.config.set(data_dir=str(reference/'satpy_geocolor_v060'),download_aux=False,
                     config_path=[str(Path(__file__).parent/'satpy_config')],
                     tmp_dir=str(Path(root)/'scratch'))
    dask.config.set(scheduler='threads',num_workers=4,**{'array.chunk-size':'16MiB'})
    return reference


def open_scene(root, plan, descriptor):
    sensor = descriptor['sensor']
    if sensor not in SUPPORTED:
        raise ValueError(f'{sensor}: no approved stock GeoColor recipe; no fallback')
    if sensor.startswith('meteosat'):
        config = json.loads((Path(root)/'project.json').read_text(encoding='utf-8')) if (Path(root)/'project.json').is_file() else {}
        if not config.get('allow_seviri_natural_color'):
            raise ValueError('SEVIRI has no approved stock GeoColor; explicit natural-colour exception required')
    records = [r for r in plan['records'] if r['scene_id']==descriptor['scene_id']]
    paths = [target_for(root,r) for r in records]
    if not paths or any(not p.is_file() or p.stat().st_size!=r['size'] for p,r in zip(paths,records)):
        raise ValueError('Incomplete archived scene')
    inputs = reader_paths(root,descriptor['scene_id'],paths) if sensor.startswith('goes') else paths
    if sensor=='himawari8':
        from .hsd_cache import expand
        inputs=expand(inputs,root,descriptor['scene_id'])
    reader,bands = RECIPES[sensor]
    if sensor.startswith('meteosat'): bands = SEVIRI_BANDS
    scene = Scene(reader=reader,filenames=[str(p) for p in inputs])
    scene.load(bands)
    return scene,records


def validate_compute_chunk(value):
    if isinstance(value,bool) or not isinstance(value,int) or value not in (512,1024,2048):
        raise ValueError('compute_chunk must be512,1024 or2048; native pixels are unchanged')
    return value


def inject_background(scene, area, night_path, cache_root=None, night_io='packed',compute_chunk=512):
    compute_chunk=validate_compute_chunk(compute_chunk)
    if night_io not in ('packed','mmap'):
        raise ValueError('Unknown lossless night input representation')
    values = read_on_area(night_path,area,cache_root=cache_root)
    if night_io=='packed' and isinstance(values,np.memmap) and area.width*area.height>=5_000_000:
        from .night_packing import packed
        values=packed(values)
    x,y=area.get_proj_vectors()
    # Identical semantics to StaticImageCompositor/generic_image: RGB 0..255,
    # standard_name night_background; stock enhancer performs its own scaling.
    scene['_night_background_hires'] = xr.DataArray(da.from_array(ReadOnlyArray(values),chunks=(3,compute_chunk,compute_chunk),
        asarray=False,fancy=False,name=False,meta=np.empty((0,0,0),np.float32)),
        dims=('bands','y','x'),coords={'bands':['R','G','B'],'x':x,'y':y},
        attrs={'name':'_night_background_hires','standard_name':'night_background',
               'area':area,'sensor':None,'mode':'RGB'})


def align_sensor(scene,target,native_tile=False,compute_chunk=512):
    scene=scene.crop(xy_bbox=target.area_extent)
    if native_tile:
        target=scene.finest_area()
    result=scene.resample(target,resampler='native')
    target=result.finest_area()
    x,y=target.get_proj_vectors()
    for key in list(result.keys()):
        # A cropped fine band can retain sliced full-disk float coordinates;
        # repeated coarser bands receive newly generated coordinates differing
        # by a few ULPs. Xarray would inner-join and silently drop rows/columns.
        if result[key].shape!=target.shape: raise ValueError('Native sensor grids failed to align')
        result[key]=result[key].assign_coords(x=x,y=y).chunk({'x':compute_chunk,'y':compute_chunk})
    return result,target


def compose(scene, target, night_path, reference, native=False, composite='geo_color',native_tile=False,night_cache=None,night_io='packed',compute_chunk=512,retain_datasets=()):
    compute_chunk=validate_compute_chunk(compute_chunk)
    # Native tiles are sliced in sensor space before native aggregation/repeat.
    # Proxies use nearest navigation. Neither is an independent colour algorithm.
    if native:
        # Satpy rounds multiresolution crops to the coarsest footprint. The
        # native tile keeps the actual red-grid halo, without forced resizing.
        result,target=align_sensor(scene,target,native_tile,compute_chunk=compute_chunk)
    else:
        result = scene.resample(target,resampler='nearest',radius_of_influence=6000)
    raw_names = [str(key['name']) for key in result.keys()]
    support = observed_support(result, raw_names)
    inject_background(result,target,night_path,night_cache,night_io=night_io,compute_chunk=compute_chunk)
    result.load([composite, *retain_datasets])
    ancillary = [k for k in result.keys() if result[k].attrs.get('area')!=target]
    static_keys=[k for k in ancillary if result[k].attrs.get('standard_name')=='land_water_mask']
    if night_cache is not None and static_keys:
        from .static_mask_cache import cached
        mask_file=reference/'satpy_geocolor_v060/composites/gshhs_land_water_mask_3km_i.tif'
        for key in static_keys:
            result[key]=cached(result[key],target,mask_file,Path(night_cache).parent/'static_landmask_grids_v1',compute_chunk=compute_chunk)
        ancillary=[k for k in ancillary if k not in static_keys]
    if ancillary:
        aligned = result.resample(target,datasets=ancillary,generate=False,
                                  resampler='nearest',radius_of_influence=6000)
        x,y=target.get_proj_vectors()
        for key in ancillary: result[key] = aligned[key].assign_coords(x=x,y=y).chunk({'x':compute_chunk,'y':compute_chunk})
    result.generate_possible_composites(unload=True)
    if composite not in result:
        raise RuntimeError('Stock composite dependencies unavailable: '+str(result.missing_datasets))
    # Stock background alone must never turn an unobserved hemisphere into data.
    # Restrict to primary same-scan visible + thermal-window IR support.
    # Cold 3.9um noise is handled by stock low-cloud logic, not a scan veto.
    result[composite] = result[composite].where(support)
    return result,target


def export_scene(root,plan,descriptor,target,kind,night_path,native=False,sensor_native=False,opened=None):
    began=perf_counter()
    reference = configure(root)
    folder = Path(root)/'processed/stock_geocolor'/descriptor['scene_id']/kind
    folder.mkdir(parents=True,exist_ok=True)
    metadata_path = folder/'metadata.json'
    if metadata_path.exists():
        old = json.loads(metadata_path.read_text(encoding='utf-8'))
        if (old.get('profile')==PROFILE and old.get('night_navigation_version')==2 and old.get('observation_support_version')==SUPPORT_VERSION and old.get('night_background_sha256')==sha(night_path)
                and sha(folder/'geo_color.tif')==old['sha256']):
            return metadata_path
        raise ValueError('Existing stock output identity differs; preserved')
    check_disk(root,target.width*target.height*32)
    scene,records = opened if opened is not None else open_scene(root,plan,descriptor)
    grid_record = {name:{'shape':list(scene[name].shape),'resolution_m':scene[name].attrs.get('resolution'),
        'actual_start_utc':observation_interval(scene[name].attrs)[0],
        'actual_end_utc':observation_interval(scene[name].attrs)[1]} for name in
        (SEVIRI_BANDS if descriptor['sensor'].startswith('meteosat') else RECIPES[descriptor['sensor']][1])}
    composite = composite_name(descriptor['sensor'])
    planning=perf_counter()
    result,area = compose(scene,target,night_path,reference,native or sensor_native,composite,native_tile=native,
                          night_cache=Path(root)/'processed/static_night_grids_v1')
    composed=perf_counter()
    output = folder/'geo_color.tif'; part = folder/'geo_color.part.tif'
    from .spill import bounded_compute
    with bounded_compute(Path(root)), ComputeProgress(Path(root)/'reports/compute_progress.json',descriptor['scene_id']):
        result.save_dataset(composite,filename=str(part),writer='geotiff',
            dtype=np.uint8,compress='DEFLATE',tiled=True,blockxsize=256,blockysize=256,
            predictor=2,
            include_scale_offset_tags=False)
    written=perf_counter()
    with rasterio.open(part) as src:
        if src.shape!=area.shape or src.count not in (3,4):
            raise ValueError('Expected georeferenced stock RGBA output')
        valid=0
        for _,window in src.block_windows(1):
            alpha=src.read(4,window=window) if src.count==4 else src.dataset_mask(window=window)
            valid+=int(np.count_nonzero(alpha))
        if not valid: raise EmptyObservation('Empty stock GeoColor output')
    part.replace(output)
    info = {'profile':PROFILE,'night_navigation_version':2,'observation_support_version':SUPPORT_VERSION,'satpy_version':satpy.__version__,'composite':composite,
        'stock_recipes_and_enhancements':composite=='geo_color',
        'execution_optimization':'stock-low-cloud-equivalent-concat-v1',
        'execution_optimization_sha256':sha(Path(__file__).parent/'satpy_execution.py'),
        'memory_execution':'import-time512-coordinates-two-threads-2GiB-lossless-array-spill',
        'ahi_bounded_count_reader':descriptor['sensor']=='himawari8',
        'seviri_natural_color_exception':composite!='geo_color',
        'seviri_adaptation_sha256':sha(Path(__file__).parent/'satpy_config/composites/seviri.yaml') if composite!='geo_color' else None,
        'night_background_only_replaced':True,
        'night_reference_year':2016,'night_background':str(night_path),
        'night_background_sha256':sha(night_path),'sensor':descriptor['sensor'],
        'nominal_utc':descriptor['nominal_utc'],'scene_id':descriptor['scene_id'],
        'shape':list(area.shape),'extent':list(area.area_extent),'crs_wkt':area.crs.to_wkt(),
        'source_bands':grid_record,'source_files':[str(target_for(root,r)) for r in records],
        'sha256':sha(output),'bytes':output.stat().st_size,'finite_alpha_pixels':valid,
        'native_grid_tile':native,'proxy':not native,
        'limits':'Same-scan surface image, not 3D clouds. 500m red does not make RGB/IR independently 500m. Coastline registration pending.'}
    save(metadata_path,info)
    timing={'scene_id':descriptor['scene_id'],'kind':kind,'shape':list(area.shape),
            'open_and_metadata_seconds':planning-began,'planning_and_static_night_seconds':composed-planning,
            'satpy_and_tiff_seconds':written-composed,'validation_and_commit_seconds':perf_counter()-written,
            'total_export_seconds':perf_counter()-began}
    with (Path(root)/'reports/performance.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(timing)+'\n')
    del scene,result; gc.collect()
    return metadata_path
