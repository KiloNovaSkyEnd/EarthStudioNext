"""Camera-requested geographic cells from original sensor grids.

The 5 degree cells are an index, not a global texture limit. Each has a shared
one-pixel halo and 1280 interior samples (~434m at the equator), retaining the
available 500m measurements without pretending coarser RGB/IR gains detail.
"""
import gc
import json
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject,Resampling
from pyproj import Transformer
from .project import save,check_disk
from .stock import configure,open_scene,export_scene,SUPPORTED,EmptyObservation
from .fusion import fuse
from .archive import sha

SIZE=1280
SPAN=5


def coarse_disk_factor(area,nominal_resolution):
    """Use the sensor's declared resolution, not rounded projection metres."""
    factor=1
    while (nominal_resolution*factor*2<=2000 and
           area.width%(factor*2)==0 and area.height%(factor*2)==0):
        factor*=2
    return factor


def cell_bounds(column,row,level=0):
    if not isinstance(level,int) or not 0<=level<=3: raise ValueError('Invalid LOD level')
    span=SPAN*2**level
    if not (isinstance(level,int) and 0<=level<=3 and isinstance(column,int) and isinstance(row,int)
            and 0<=column<360//span and 0<=row<int(np.ceil(180/span))):
        raise ValueError('Invalid geographic cell index')
    west=-180+column*span; south=-90+row*span
    return west,south,west+span,min(90,south+span)


def sensor_crop(area,bounds):
    """Navigate real geographic samples, then retain a native-grid halo."""
    west,south,east,north=bounds
    lon,lat=np.meshgrid(np.linspace(west,east,65),np.linspace(south,north,65))
    x,y=Transformer.from_crs('EPSG:4326',area.crs,always_xy=True).transform(lon,lat)
    valid=np.isfinite(x)&np.isfinite(y)
    if not valid.any(): return None
    left,bottom,right,top=area.area_extent
    cols=(x[valid]-left)/area.pixel_size_x
    rows=(top-y[valid])/area.pixel_size_y
    c0=max(0,int(np.floor(cols.min()/4))*4-16)
    c1=min(area.width,int(np.ceil(cols.max()/4))*4+16)
    r0=max(0,int(np.floor(rows.min()/4))*4-16)
    r1=min(area.height,int(np.ceil(rows.max()/4))*4+16)
    if c1<=c0 or r1<=r0: return None
    return area[slice(r0,r1),slice(c0,c1)]


def source_candidates(root,descriptors,cells):
    """Use genuine proxy support plus a conservative angular margin.

    All source pixels stay untouched. This avoids recomputing far-away views
    that cannot win the existing two-degree navigation feather.
    """
    navigation=[]
    for descriptor in descriptors:
        kind='disk_proxy_12km' if descriptor['sensor'].startswith('meteosat') else 'disk_proxy_8km'
        path=Path(root)/'processed/stock_geocolor'/descriptor['scene_id']/kind/'geo_color.tif'
        if not path.is_file(): return {cell:{d['scene_id'] for d in descriptors} for cell in cells}
        with rasterio.open(path) as source:
            mask=source.read(4) if source.count==4 else source.dataset_mask()
            navigation.append((descriptor['scene_id'],mask,~source.transform,
                Transformer.from_crs('EPSG:4326',source.crs,always_xy=True),source.crs.to_dict()['lon_0']))
    chosen={}
    for cell in cells:
        west,south,east,north=cell_bounds(*cell)
        lon,lat=np.meshgrid(np.linspace(west,east,65),np.linspace(south,north,65))
        scores=[]
        for scene_id,mask,inverse,projection,lon0 in navigation:
            x,y=projection.transform(lon,lat); col,row=inverse*(x,y)
            valid=np.isfinite(col)&np.isfinite(row)&(col>=0)&(row>=0)&(col<mask.shape[1])&(row<mask.shape[0])&(np.abs(lat)<70)
            c=np.zeros(lon.shape,int); r=np.zeros(lat.shape,int)
            c[valid]=col[valid].astype(int); r[valid]=row[valid].astype(int)
            valid&=mask[r,c]>0
            distance=np.arccos(np.clip(np.cos(np.deg2rad(lat))*np.cos(np.deg2rad(lon-lon0)),-1,1))
            scores.append(np.where(valid,distance,np.inf))
        best=np.minimum.reduce(scores)
        chosen[cell]={item[0] for item,score in zip(navigation,scores)
                      if np.any(np.isfinite(score)&(score<=best+np.deg2rad(5)))}
    return chosen


def process(root,request_file):
    root=Path(root).resolve(); request_file=Path(request_file).resolve()
    from .gpu import device
    save(root/'reports/gpu_compute.json',device())
    requests_root=(root/'requests').resolve()
    if not request_file.is_relative_to(requests_root): raise ValueError('Request must be inside project requests/')
    request=json.loads(request_file.read_text(encoding='utf-8'))
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    jobs=request['nodes']
    if not jobs or len(jobs)>73: raise ValueError('Expected 1..73 real observation nodes')
    for job in jobs:
        if job['nominal_utc'] not in plan['frames']: raise ValueError('UTC outside archive timeline')
        if len(job['cells'])>512: raise ValueError('Request too large; split the camera range')
        for cell in job['cells']: cell_bounds(*cell)
    night=root/'raw/references/blackmarble_2016_500m/global_500m.vrt'
    destination=root/'processed/stock_geocolor/camera_cells_v1'
    result_file=request_file.with_suffix('.result.json')
    status_file=request_file.with_suffix('.status.json')
    def status(stage,**values):
        record={'stage':stage,'updated_utc':datetime.now(timezone.utc).isoformat(),**values}
        save(status_file,record); print(json.dumps(record,ensure_ascii=False),flush=True)
    import msvcrt
    with (root/'reports/stock_job.lock').open('a+b') as lock:
        lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        results=[]
        try:
            for node,job in enumerate(jobs,1):
                utc=job['nominal_utc']; descriptors=[s for s in plan['scenes'] if s['nominal_utc']==utc and s['sensor'] in SUPPORTED]
                cells=[tuple(v) for v in job['cells']]
                paths={cell:[] for cell in cells}
                pending=[]
                for cell in cells:
                    level=cell[2] if len(cell)>2 else 0
                    folder=destination/utc.replace(':','').replace('-','')/f'l{level}_c{cell[0]:02d}_r{cell[1]:02d}'
                    committed=folder/'tile.json'
                    if committed.is_file():
                        record=json.loads(committed.read_text(encoding='utf-8'))
                        if sha(Path(record['texture']))!=record['sha256']: raise ValueError('Committed camera texture changed')
                        results.append({**record,'display_frames':job['display_frames']})
                    else: pending.append(cell)
                if not pending: continue
                candidates=source_candidates(root,descriptors,pending)
                for descriptor in descriptors:
                    # Real source support decides final ownership. Invisible
                    # hemispheres are rejected by projection, never filled.
                    cached_scene=None; records=None; disk_paths={}
                    for cell in pending:
                        if descriptor['scene_id'] not in candidates[cell]: continue
                        c,r=cell[:2]; level=cell[2] if len(cell)>2 else 0
                        bounds=cell_bounds(c,r,level)
                        dx=(bounds[2]-bounds[0])/SIZE; dy=(bounds[3]-bounds[1])/SIZE
                        expanded=(bounds[0]-dx,bounds[1]-dy,bounds[2]+dx,bounds[3]+dy)
                        if bounds[1]>=70 or bounds[3]<=-70: continue
                        kind=f'camera_cell_v1_l{level}_c{c:02d}_r{r:02d}'
                        existing=root/'processed/stock_geocolor'/descriptor['scene_id']/kind/'metadata.json'
                        if existing.is_file():
                            paths[cell].append(export_scene(root,plan,descriptor,None,kind,night,native=level==0,sensor_native=level>0)); continue
                        # Discard sensors entirely beyond the visible limb
                        # using the static projection of a cached proxy.
                        proxy_kind='disk_proxy_12km' if descriptor['sensor'].startswith('meteosat') else 'disk_proxy_8km'
                        proxy=root/'processed/stock_geocolor'/descriptor['scene_id']/proxy_kind/'geo_color.tif'
                        if proxy.is_file():
                            from pyresample.geometry import AreaDefinition
                            with rasterio.open(proxy) as src:
                                mock=AreaDefinition('disk','','',src.crs.to_dict(),src.width,src.height,tuple(src.bounds))
                            if sensor_crop(mock,expanded) is None: continue
                        status('native_sensor_cell',node=node,total=len(jobs),utc=utc,sensor=descriptor['sensor'],cell=cell)
                        if level==3:
                            if level not in disk_paths:
                                disk_kind='camera_disk_2km_v1'
                                existing_disk=root/'processed/stock_geocolor'/descriptor['scene_id']/disk_kind/'metadata.json'
                                if existing_disk.is_file():
                                    disk_paths[level]=export_scene(root,plan,descriptor,None,disk_kind,night,sensor_native=True)
                                else:
                                    if cached_scene is None:
                                        configure(root); cached_scene,records=open_scene(root,plan,descriptor)
                                    area=cached_scene.finest_area()
                                    nominal=min(float(band.attrs['resolution']) for band in cached_scene.values())
                                    factor=coarse_disk_factor(area,nominal)
                                    target=area.copy(width=area.width//factor,height=area.height//factor)
                                    disk_paths[level]=export_scene(root,plan,descriptor,target,disk_kind,night,
                                        sensor_native=True,opened=(cached_scene,records))
                            paths[cell].append(disk_paths[level]); continue
                        if cached_scene is None:
                            configure(root); cached_scene,records=open_scene(root,plan,descriptor)
                        crop=sensor_crop(cached_scene.finest_area(),expanded)
                        if crop is None: continue
                        if level>0:
                            factor=1
                            desired=434*2**level
                            while crop.pixel_size_x*(factor*2)<=desired and crop.width%(factor*2)==0 and crop.height%(factor*2)==0:
                                factor*=2
                            crop=crop.copy(width=crop.width//factor,height=crop.height//factor)
                        try:
                            paths[cell].append(export_scene(root,plan,descriptor,crop,kind,night,native=level==0,
                                sensor_native=level>0,opened=(cached_scene,records)))
                        except EmptyObservation:
                            status('source_has_no_support',utc=utc,sensor=descriptor['sensor'],cell=cell)
                    del cached_scene; gc.collect()
                for cell in pending:
                    bounds=cell_bounds(*cell)
                    dx=(bounds[2]-bounds[0])/SIZE; dy=(bounds[3]-bounds[1])/SIZE
                    expanded=(bounds[0]-dx,bounds[1]-dy,bounds[2]+dx,bounds[3]+dy)
                    size=SIZE+2; transform=from_bounds(*expanded,size,size)
                    lon,lat=np.meshgrid(expanded[0]+(np.arange(size)+.5)*dx,
                                        expanded[3]-(np.arange(size)+.5)*dy)
                    inputs=[]
                    for metadata in paths[cell]:
                        pixels=np.zeros((4,size,size),np.uint8)
                        with rasterio.open(metadata.parent/'geo_color.tif') as src:
                            for band in range(1,min(src.count,4)+1):
                                reproject(rasterio.band(src,band),pixels[band-1],src_transform=src.transform,
                                    src_crs=src.crs,dst_transform=transform,dst_crs='EPSG:4326',
                                    resampling=Resampling.nearest,num_threads=2,warp_mem_limit=64)
                            if src.count==3:
                                reproject(src.dataset_mask(),pixels[3],src_transform=src.transform,src_crs=src.crs,
                                    dst_transform=transform,dst_crs='EPSG:4326',resampling=Resampling.nearest)
                            lon0=src.crs.to_dict()['lon_0']
                        inputs.append((pixels.transpose(1,2,0),lon0))
                    pixels,owners,_=fuse(inputs,lon,lat,backend='cuda')
                    level=cell[2] if len(cell)>2 else 0
                    folder=destination/utc.replace(':','').replace('-','')/f'l{level}_c{cell[0]:02d}_r{cell[1]:02d}'
                    folder.mkdir(parents=True,exist_ok=True); check_disk(root,pixels.nbytes*3)
                    texture=folder/'weather.png'; temporary=folder/'weather.part.png'
                    Image.fromarray(pixels).save(temporary); temporary.replace(texture)
                    record={'cell':cell,'bounds':bounds,'texture_bounds':expanded,'texture':str(texture),
                        'nominal_utc':utc,'sha256':sha(texture),'size':size,'halo_pixels':1,
                        'sources':[str(p) for p in paths[cell]],'valid_fraction':float(np.mean(owners>0)),
                        'level':level,'display_sampling_equator_m':434*2**level,
                        'native_source_grid_preserved':True,'independent_rgb_resolution_m':'Sensor bands retain their genuine 0.5/1/2/3km detail; 434m display sampling adds no measurements.'}
                    save(folder/'tile.json',record)
                    results.append({**record,'display_frames':job['display_frames']})
                status('node_ready',node=node,total=len(jobs),utc=utc)
            result={'tiles':results,'request':str(request_file),'all_requested_cells_committed':True,
                    'global_native_precomputed':False,'visual_acceptance_passed':False}
            save(result_file,result); status('ready',tiles=len(results),result=str(result_file)); return result_file
        except Exception as error:
            status('failed',error=str(error)); raise
