"""Resumable bounded pilot; report partial coverage rather than fake a globe."""
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import traceback
import faulthandler
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject,Resampling
from pyproj import Transformer
from .capabilities import inspect
from .project import save
from .stock import configure,open_scene,export_scene,SUPPORTED
from .night_background import make_proxy
from .fusion import fuse


def combine_proxy(root, paths, index, utc, folder_name='global_proxy',width=2048):
    """Navigation-only source selection, no custom colour adjustment or fill."""
    height=width//2
    transform = from_bounds(-180,-90,180,90,width,height)
    inputs=[]
    lon = -180+(np.arange(width)+.5)*360/width
    lat = 90-(np.arange(height)+.5)*180/height
    longitude,latitude = np.meshgrid(lon,lat)
    for number,path in enumerate(paths,1):
        info = json.loads(path.read_text(encoding='utf-8'))
        tile = np.zeros((4,height,width),np.uint8)
        with rasterio.open(path.parent/'geo_color.tif') as src:
            for band in range(1,5):
                reproject(rasterio.band(src,band),tile[band-1],src_transform=src.transform,
                    src_crs=src.crs,dst_transform=transform,dst_crs='EPSG:4326',
                    resampling=Resampling.nearest,num_threads=2,warp_mem_limit=64)
            lon0 = src.crs.to_dict()['lon_0']
        inputs.append((tile.transpose(1,2,0),lon0))
    rgb,owner,weight=fuse(inputs,longitude,latitude)
    folder = Path(root)/'processed/stock_geocolor'/folder_name
    folder.mkdir(parents=True,exist_ok=True)
    output = folder/f'weather_{index:04d}.png'
    part = output.with_suffix('.part.png'); Image.fromarray(rgb).save(part); part.replace(output)
    Image.fromarray(owner).save(folder/f'sources_{index:04d}.png')
    info = {'nominal_utc':utc,'frame':index,'file':str(output),'proxy_shape':[height,width],
        'extent':[-180,-90,180,90],'crs':'EPSG:4326','sources':[str(p) for p in paths],
        'valid_nonpolar_pixel_fraction':float(np.count_nonzero(owner)/np.count_nonzero(np.abs(latitude)<70)),
        'global_acceptance_passed':False,'missing_is_transparent':True,
        'source_selection':'Nearest angular distance; 2 degree score-margin feather between two valid views in linear light. No colour correction.',
        'geographic_feathered_pixels':int(np.count_nonzero(weight)),
        'target_latitude_limit_degrees':70,
        'source_labels':{str(i):json.loads(p.read_text(encoding='utf-8'))['composite'] for i,p in enumerate(paths,1)},
        'limits':'Navigation pilot; SEVIRI uses explicitly adapted natural colour. No complete global coverage or final native-resolution claim.'}
    from ges.catalog import utc_time
    from ges.solar import sun_direction
    info['sun']=sun_direction(utc_time(utc)).tolist()
    save(output.with_suffix('.json'),info)
    return info


def run(root):
    faulthandler.enable()
    root = Path(root)
    status = root/'reports/stock_job_status.json'
    def update(stage,**values):
        record = {'stage':stage,'updated_utc':datetime.now(timezone.utc).isoformat(),**values}
        save(status,record); print(json.dumps(record,ensure_ascii=False),flush=True)
    import msvcrt
    lock = root/'reports/stock_job.lock'
    with lock.open('a+b') as stream:
        if stream.tell()==0: stream.write(b'0'); stream.flush()
        stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        try:
            update('checking_archive')
            report = inspect(root)
            if report['archive_receipt_problems']: raise ValueError('Archive integrity preflight failed')
            night = root/'raw/references/blackmarble_2016_500m/global_500m.vrt'
            if not night.is_file(): raise FileNotFoundError('Complete verified 500m night mosaic required first')
            update('building_shared_night_proxy')
            make_proxy(night)
            plan = json.loads((root/'inventory.json').read_text(encoding='utf-8'))
            results = []
            # Three timestamps exercise the night-to-day transition without
            # silently claiming that this sparse pilot is the 73-node sequence.
            for index,frame in enumerate((plan['frames'][0],plan['frames'][36],plan['frames'][-1]),1):
                paths = []
                for descriptor in (s for s in plan['scenes'] if s['nominal_utc']==frame and s['sensor'] in SUPPORTED):
                    update('stock_proxy',frame=index,nominal_utc=frame,sensor=descriptor['sensor'],scene_id=descriptor['scene_id'])
                    kind='disk_proxy_12km' if descriptor['sensor'].startswith('meteosat') else 'disk_proxy_8km'
                    existing=root/'processed/stock_geocolor'/descriptor['scene_id']/kind/'metadata.json'
                    if existing.is_file():
                        paths.append(export_scene(root,plan,descriptor,None,kind,night,sensor_native=True))
                        continue
                    configure(root); scene,records = open_scene(root,plan,descriptor)
                    infrared = ('B13' if descriptor['sensor']=='himawari8' else
                                'IR_108' if descriptor['sensor'].startswith('meteosat') else 'C13')
                    grid = scene[infrared].attrs['area']
                    factor = 4
                    target = grid.copy(width=grid.width//factor,height=grid.height//factor)
                    paths.append(export_scene(root,plan,descriptor,target,kind,night,
                                              sensor_native=True,opened=(scene,records)))
                    del scene; gc.collect()
                results.append(combine_proxy(root,paths,index,frame))
            # A same-UTC native 500m red grid tile demonstrates bounded details;
            # separate manifest explicitly prevents a global-native claim.
            descriptor = next(s for s in plan['scenes'] if s['sensor']=='himawari8' and s['nominal_utc']==plan['frames'][-1])
            update('native_tile',sensor='himawari8',nominal_utc=descriptor['nominal_utc'],scene_id=descriptor['scene_id'])
            configure(root); scene,records = open_scene(root,plan,descriptor)
            area = scene['B03'].attrs['area']
            x,y = Transformer.from_crs('EPSG:4326',area.crs,always_xy=True).transform(127,25)
            left,bottom,right,top = area.area_extent
            col = int((x-left)/area.pixel_size_x)//4*4
            row = int((top-y)/area.pixel_size_y)//4*4
            tile = area[slice(row-512,row+512),slice(col-512,col+512)]
            detail = export_scene(root,plan,descriptor,tile,'native_detail_127E_25N',night,
                                  native=True,opened=(scene,records))
            del scene; gc.collect()
            from .registration import verify
            update('night_registration')
            verify(root,detail)
            save(root/'reports/stock_pilot.json',{'frames':results,'native_detail':str(detail),
                'global_blockers':report['global_blockers'],'complete_sequence':False,
                'visual_acceptance_passed':False,'global_acceptance_passed':False})
            from .blender_assets import prepare as prepare_blender
            prepare_blender(root,{'frames':results,'native_detail':str(detail)})
            update('pilot_assets_ready',frames=3,global_blockers=report['global_blockers'],
                   full_sequence=False,global_acceptance_passed=False)
        except Exception as error:
            update('failed',error_type=type(error).__name__,error=str(error))
            traceback.print_exc(); raise
