"""Exact requested H9 scan, sensor-native stock GeoColor tiles; archives read only."""
import argparse, gc, hashlib, json, os, shutil, sys, time
from pathlib import Path
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def main():
    execution_began=time.time()
    parallel_used=False
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True);parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--night',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--utc',default='2026-10-20T22:40:00Z',help='Exact UTC scan start; no nearest-time substitution')
    parser.add_argument('--shared-static-cache',type=Path,help='Reuse only immutable night/landmask navigation across scans')
    parser.add_argument('--performance-profile',type=Path,help='Explicit qualified profile for isolated performance validation')
    parser.add_argument('--scope-generation',type=int,default=1)
    parser.add_argument('--row',type=int,choices=[0,5500,11000,16500]);parser.add_argument('--assemble-only',action='store_true')
    args=parser.parse_args()
    static_cache=require_writable(args.shared_static_cache) if args.shared_static_cache else None
    if static_cache:
        scope=static_cache.parent/'requested_scope.json'
        if scope.exists() and json.loads(scope.read_text(encoding='utf-8'))['generation']>args.scope_generation:
            print('SCOPE_HANDOFF_REQUIRED: finishing old scope at scan boundary; replacement owns expanded plan',flush=True)
            raise SystemExit(75)
    from datetime import datetime,timezone
    stamp=datetime.fromisoformat(args.utc.replace('Z','+00:00'))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds()!=0 or stamp.second or stamp.microsecond or stamp.minute%10:
        raise ValueError('An exact ten-minute UTC scan start is required')
    stamp=stamp.astimezone(timezone.utc);utc_label=stamp.isoformat().replace('+00:00','Z')
    if static_cache and args.row is None and not args.assemble_only:
        from ges_next.h9_performance_window import wait_for_window
        from ges.earth_validation.project import save
        wait_for_window(static_cache.parent,utc_label,args.scope_generation,
            report=lambda state:save(static_cache.parent/'reports/performance_window_status.json',state))
        if scope.exists() and json.loads(scope.read_text(encoding='utf-8'))['generation']>args.scope_generation:
            raise SystemExit(75)
        # Exclude intentional research waiting from native execution timing.
        execution_began=time.time()
    out=require_writable(args.output);out.mkdir(parents=True,exist_ok=True)
    existing=out/'native_master.json'
    if existing.exists() and json.loads(existing.read_text(encoding='utf-8'))['utc']!=utc_label:
        raise ValueError('Output already belongs to a different observation; choose another directory')
    for prior in out.glob('input_inventory*.json'):
        if json.loads(prior.read_text(encoding='utf-8'))['utc']!=utc_label:
            raise ValueError('Existing row output belongs to another UTC scan')
    if any(out.glob('native_*.tif')) and not existing.exists() and not any(out.glob('input_inventory*.json')):
        raise ValueError('Cannot reuse native tiles with no verified observation identity')
    work=out/('work' if not args.row else f'work_{args.row}');work.mkdir(exist_ok=True)
    identity=work/'observation_identity.json'
    if identity.exists() and json.loads(identity.read_text(encoding='utf-8'))['utc']!=utc_label:
        raise ValueError('Existing intermediate tiles belong to another observation')
    write(identity,dict(utc=utc_label))
    settings=dict(start_utc=utc_label,end_utc=utc_label,reserve_free_bytes=16*1024**3,scope='H9 single full disk native test; no downloads')
    os.environ['EARTHSTUDIO_H9_CUDA_CLOUDS']='0'
    profile=args.performance_profile or (static_cache.parent/'compute_profile.json' if static_cache else None)
    parallel_rows=1
    if profile and profile.exists():
        performance=json.loads(profile.read_text(encoding='utf-8'))
        if performance.get('pixel_parity_qualified') is not True:
            raise ValueError('Unqualified compute profile cannot alter production workers')
        workers=performance['compute_workers']
        if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=8:
            raise ValueError('Invalid qualified worker count')
        settings['compute_workers']=workers
        zlevel=performance.get('zlevel',6)
        if isinstance(zlevel,bool) or not isinstance(zlevel,int) or zlevel not in (1,6):
            raise ValueError('Only qualified lossless DEFLATE levels1 and6 are supported')
        if zlevel!=6 and performance.get('lossless_level_pixel_parity_qualified') is not True:
            raise ValueError('Lossless level changes require full encoding qualification')
        if zlevel!=6 and performance.get('allow_storage_growth') is False:
            raise ValueError('Project storage policy forbids larger lossless output encoding')
        settings['zlevel']=zlevel
        compute_chunk=performance.get('compute_chunk',512)
        if isinstance(compute_chunk,bool) or not isinstance(compute_chunk,int) or compute_chunk not in (512,1024,2048):
            raise ValueError('Invalid qualified compute chunk')
        if compute_chunk!=512 and performance.get('compute_chunk_pixel_parity_qualified') is not True:
            raise ValueError('Native chunk changes require pixel parity qualification')
        settings['compute_chunk']=compute_chunk
        shared_solar=performance.get('shared_solar_factors',False)
        if not isinstance(shared_solar,bool):raise ValueError('Invalid shared solar factor setting')
        if shared_solar and performance.get('solar_factors_pixel_parity_qualified') is not True:
            raise ValueError('Shared stock solar factors require exact qualification')
        settings['shared_solar_factors']=shared_solar
        night_io=performance.get('night_io','packed')
        if night_io not in ('packed','mmap'):raise ValueError('Invalid night I/O representation')
        if night_io=='mmap' and performance.get('night_io_pixel_parity_qualified') is not True:
            raise ValueError('Lossless mmap night I/O requires pixel parity qualification')
        settings['night_io']=night_io
        if performance.get('gpu_clouds') in ('cuda','cuda-night'):
            if performance.get('cuda_full_tile_pixel_parity_qualified') is not True:
                raise ValueError('Full native-tile CUDA parity qualification required')
            settings['gpu_clouds']=performance['gpu_clouds']
            os.environ['EARTHSTUDIO_H9_CUDA_CLOUDS']='2' if performance['gpu_clouds']=='cuda-night' else '1'
        if performance.get('gdal_threads',1)!=1:
            if performance.get('encoding_pixel_parity_qualified') is not True:
                raise ValueError('Lossless threaded encoding must be qualified')
            gdal_threads=performance['gdal_threads']
            if isinstance(gdal_threads,bool) or not isinstance(gdal_threads,int) or not (1<=gdal_threads<=4 or gdal_threads==8):
                raise ValueError('Invalid qualified compression thread count')
            if gdal_threads==8 and performance.get('encoding_threads8_pixel_parity_qualified') is not True:
                raise ValueError('Eight encoder threads require dedicated pixel qualification')
            settings['gdal_threads']=gdal_threads
        parallel_rows=performance.get('parallel_rows',1)
        if parallel_rows!=1 and performance.get('process_pixel_parity_qualified') is not True:
            raise ValueError('Independent-process pixel qualification required')
    write(work/'project.json',settings)
    files=sorted(args.raw.glob(f'HS_H09_{stamp:%Y%m%d_%H%M}_*.DAT'))
    required={(band,segment) for band in ['B01','B02','B03','B04','B07','B13'] for segment in range(1,11)}
    import re
    actual=[]
    for path in files:
        match=re.search(r'_(B\d{2})_FLDK_R\d{2}_S(\d{2})10\.DAT$',path.name)
        if match:actual.append((match[1],int(match[2])))
    if len(files)!=60 or len(actual)!=60 or set(actual)!=required:
        raise ValueError('Exact H9 UTC scan requires all 60 unique native segments of the six GeoColor bands')
    if shutil.disk_usage(out).free<25*1024**3:raise ValueError('Need 25GiB scratch/output reserve')
    records=[dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=digest(p)) for p in files]
    write(out/('input_inventory.json' if args.row is None else f'input_inventory_{args.row}.json'),dict(utc=utc_label,files=records,night=str(args.night.resolve()),downloads=0))
    if parallel_rows>1 and args.row is None and not args.assemble_only:
        from ges_next.h9_parallel import admitted_rows,dispatch_rows
        from ges.earth_validation.resources import commit_usage
        import psutil
        commit=commit_usage()
        available=psutil.virtual_memory().available
        admitted=admitted_rows(parallel_rows,available,commit.get('available_bytes',available))
        write(out/'parallel_row_admission.json',dict(requested_rows=parallel_rows,admitted_rows=admitted,
            physical_available_bytes=available,commit_available_bytes=commit.get('available_bytes'),
            reserve_physical_bytes=6*1024**3,reserve_commit_bytes=2*1024**3))
        print('PARALLEL_NATIVE_ROWS',admitted,'independent processes; unchanged16 native tiles',flush=True)
        if dispatch_rows(args,Path(__file__).resolve(),admitted):
            parallel_used=True
            # Children publish exact per-tile receipts; the normal loop verifies and assembles them.
            args.assemble_only=True
        else:
            print('MEMORY_BOUNDED_SINGLE_SCENE: reuse qualified in-process16-tile route',flush=True)
    from ges.earth_validation import stock
    from ges.earth_validation.spill import bounded_compute
    from ges.earth_validation.resources import monitor,gpu_sample,spill_sample
    from ges.earth_validation.compute_progress import ComputeProgress
    import satpy, yaml, rasterio, numpy as np
    from rasterio.transform import from_bounds
    from satpy import Scene
    stock.configure(work)
    runtime=work/'scratch/pyspectral_runtime.yaml'
    runtime.write_text(yaml.safe_dump(dict(download_from_internet=False,rayleigh_dir=str(args.reference/'pyspectral'),rsr_dir=str(args.reference/'pyspectral/rsr'))),encoding='utf-8')
    os.environ['PSP_CONFIG_FILE']=str(runtime.resolve())
    satpy.config.set(data_dir=str(args.reference/'satpy_geocolor_v060'),download_aux=False)
    if settings.get('gpu_clouds')=='cuda-night' or settings.get('shared_solar_factors'):
        base=Path(__file__).resolve().parents[1]/'ges/earth_validation'
        paths=[str(base/'satpy_config')]
        if settings.get('gpu_clouds')=='cuda-night':paths.append(str(base/'cuda_satpy_config'))
        if settings.get('shared_solar_factors'):paths.append(str(base/'solar_satpy_config'))
        satpy.config.set(config_path=paths)
    from ges.earth_validation.solar_shared import factor_sample
    scene=Scene(reader='ahi_hsd',filenames=[str(p) for p in files]);scene.load(['B01','B02','B03','B04','B07','B13'])
    area=scene['B03'].attrs['area']
    def utc(v):return v.isoformat()+'Z' if v is not None and v.tzinfo is None else str(v)
    band_info={name:dict(shape=list(scene[name].shape),resolutionMetres=float(scene[name].attrs['resolution']),startUtc=utc(scene[name].attrs.get('start_time')),endUtc=utc(scene[name].attrs.get('end_time'))) for name in ['B01','B02','B03','B04','B07','B13']}
    if area.shape!=(22000,22000):raise ValueError('Expected original 500m red grid')
    print('NATIVE_GRID',area.shape,flush=True);began=time.time();tiles=[]
    for row in range(0,22000,5500):
      if args.row is not None and row!=args.row:continue
      for col in range(0,22000,5500):
        stem=f'native_{row:05}_{col:05}';path=out/(stem+'.tif');receipt=out/(stem+'.json')
        if receipt.exists():
            meta=json.loads(receipt.read_text(encoding='utf-8'))
            if digest(path)!=meta['sha256']:raise ValueError('Existing native tile changed')
        else:
            if args.assemble_only:raise ValueError('Native tile not committed yet')
            print('COMPOSE',row,col,flush=True)
            target=area[row:row+5500,col:col+5500]
            planning_started=time.time()
            result,target=stock.compose(scene,target,args.night,args.reference,native=True,native_tile=True,night_cache=(static_cache/'night_grids') if static_cache else work/'processed/night_grids',night_io=settings.get('night_io','packed'),compute_chunk=settings.get('compute_chunk',512))
            planning_seconds=time.time()-planning_started
            part=path.with_suffix('.part.tif')
            compute_started=time.time()
            gpu_before={key:gpu_sample.get(key,0) for key in ('calls','pixels')}
            solar_before=factor_sample.copy()
            with bounded_compute(work),monitor(work),ComputeProgress(work/'reports/compute_progress.json',f'H9 {utc_label} {row},{col}'):
                result.save_dataset('geo_color',filename=str(part),writer='geotiff',dtype=np.uint8,compress='DEFLATE',tiled=True,blockxsize=256,blockysize=256,predictor=2,zlevel=settings.get('zlevel',6),num_threads=settings.get('gdal_threads',1),include_scale_offset_tags=False)
                actual_compute=dict(requested_workers=spill_sample.get('requested_workers'),
                    admitted_workers=spill_sample.get('admitted_workers'),
                    spilled_bytes=spill_sample.get('written_bytes'))
            compute_seconds=time.time()-compute_started
            with rasterio.open(part) as src:
                if src.count!=4 or abs(src.transform.a-500)>0.01:raise ValueError('Expected RGBA native500m')
                meta=dict(path=path.name,shape=list(src.shape),extent=list(src.bounds),transform=list(src.transform),crs=src.crs.to_wkt(),
                          phaseSeconds=dict(planning=planning_seconds,compute_and_write=compute_seconds),
                          execution=dict(requested_backend=settings.get('gpu_clouds','cpu'),
                              compute_admission=actual_compute,
                              compression='DEFLATE',zlevel=settings.get('zlevel',6),
                              gdal_threads=settings.get('gdal_threads',1),
                              night_io=settings.get('night_io','packed'),
                              compute_chunk=settings.get('compute_chunk',512),
                              shared_solar_factors=settings.get('shared_solar_factors',False),
                              solar_factor_execution={key:value-solar_before.get(key,0) for key,value in factor_sample.items()},
                              gpu_calls=gpu_sample.get('calls',0)-gpu_before['calls'],
                              gpu_pixels=gpu_sample.get('pixels',0)-gpu_before['pixels'],
                              gpu_telemetry=gpu_sample.copy()))
            part.replace(path);meta['sha256']=digest(path);write(receipt,meta)
            del result;gc.collect()
        tiles.append(meta);print('TILE_READY',len(tiles),'/16',round(time.time()-began,1),flush=True)
    if args.row is not None:return
    # Lossless virtual assembly; original pixel windows, no recompression/reprojection.
    xmin,ymin,xmax,ymax=area.area_extent;dx=area.pixel_size_x;dy=area.pixel_size_y
    vrt=ET.Element('VRTDataset',rasterXSize='22000',rasterYSize='22000');ET.SubElement(vrt,'SRS').text=area.crs.to_wkt();ET.SubElement(vrt,'GeoTransform').text=f'{xmin},{dx},0,{ymax},0,{-dy}'
    for band,color in enumerate(['Red','Green','Blue','Alpha'],1):
      node=ET.SubElement(vrt,'VRTRasterBand',dataType='Byte',band=str(band));ET.SubElement(node,'ColorInterp').text=color
      for tile in tiles:
        s=ET.SubElement(node,'SimpleSource');ET.SubElement(s,'SourceFilename',relativeToVRT='1').text=tile['path'];ET.SubElement(s,'SourceBand').text=str(band)
        h,w=tile['shape'];left,bottom,right,top=tile['extent'];x=round((left-xmin)/dx);y=round((ymax-top)/dy)
        core_row,core_col=map(int,Path(tile['path']).stem.split('_')[1:]);sx=core_col-x;sy=core_row-y
        if not (0<=sx and 0<=sy and sx+5500<=w and sy+5500<=h):raise ValueError('Native crop halo does not contain exact core')
        tile['coreWindow']=dict(row=core_row,col=core_col,sourceX=sx,sourceY=sy,width=5500,height=5500)
        ET.SubElement(s,'SrcRect',xOff=str(sx),yOff=str(sy),xSize='5500',ySize='5500');ET.SubElement(s,'DstRect',xOff=str(core_col),yOff=str(core_row),xSize='5500',ySize='5500')
    ET.ElementTree(vrt).write(out/'master.vrt',encoding='utf-8',xml_declaration=True)
    write(out/'native_master.json',dict(utc=utc_label,shape=[22000,22000],sourceBands=band_info,tiles=tiles,night=str(args.night.resolve()),recipe=stock.PROFILE,limits='Single observed hemisphere; B03 500m, color1km, IR2km; 2016 static night500m inside stock recipe; no global coverage/registration acceptance.',runSeconds=time.time()-execution_began,runSecondsScope='Whole native invocation including child rows; excludes coordinator download/decode',runMode='parallel-rows' if parallel_used else 'assemble-only' if args.assemble_only else 'sequential'))
    write(out/'manifest.json',dict(schema='earthstudio.materials.v1',earthModel='WGS84',scope='regional',defaultView=dict(targetLon=130.7,targetLat=18,heading=0,pitch=-90,rangeKm=4500,roll=0,fov=40),frames=[dict(utc=utc_label,scanStartUtc=band_info['B03']['startUtc'],scanEndUtc=band_info['B03']['endUtc'],source='Himawari-9 / AHI / 60 HSD segments',recipe='Satpy0.60 stock geo_color;500m static night input',detail='native-product',kind='geographic-tiles',bounds=[-180,-85,180,85],maximumLevel=8,tileSize=512,path='tiles/{z}/{x}/{y}.png',limits='Sensor-native22000x22000 retained in master.vrt; geographic preview tiles computed on demand. One observed hemisphere only; unobserved pixels transparent. Color1km/IR2km; registration pending.')]))
    print('COMMITTED',out,flush=True)

if __name__=='__main__':main()

