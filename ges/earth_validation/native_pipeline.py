"""Native-only full globe -> ordinary editable Blender sequence, without proxies."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import gc
import json
from pathlib import Path
import subprocess
import sys
from .project import save,check_disk,save_report
from .stock import configure,open_scene,export_scene,SUPPORTED
from .native_cells import cells,write
from .video_check import encode
from ges.catalog import utc_time
from ges.solar import sun_direction
from .resources import monitor,page_workers


def run(root,blender):
    import ctypes,msvcrt
    root=Path(root).resolve(); blender=Path(blender).resolve()
    if not blender.is_file(): raise FileNotFoundError('Blender executable missing')
    with (root/'reports/full_pipeline.lock').open('a+b') as lock:
        lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        try:
            with monitor(root): return execute(root,blender)
        finally: ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


def execute(root,blender):
    def update(stage,**values):
        item={'stage':stage,'updated_utc':datetime.now(timezone.utc).isoformat(),'native_only':True,**values}
        save_report(root/'reports/full_pipeline_status.json',item); print(json.dumps(item),flush=True)
    from .gpu import device
    save(root/'reports/gpu_compute.json',device())
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    night=root/'raw/references/blackmarble_2016_500m/global_500m.vrt'
    output=root/'exports/earth_native_only_v1'; output.mkdir(parents=True,exist_ok=True)
    jobs=cells(); nodes=[]
    try:
        check_disk(root,350_000_000_000)
        for index,utc in enumerate(plan['frames'],1):
            metadata=[]
            for descriptor in (d for d in plan['scenes'] if d['nominal_utc']==utc and d['sensor'] in SUPPORTED):
                kind='full_native_disk_v4'; existing=root/'processed/stock_geocolor'/descriptor['scene_id']/kind/'metadata.json'
                update('native_sensor_disk',node=index,total=73,utc=utc,sensor=descriptor['sensor'])
                if existing.is_file():
                    metadata.append(export_scene(root,plan,descriptor,None,kind,night,native=True))
                else:
                    configure(root); scene,records=open_scene(root,plan,descriptor)
                    metadata.append(export_scene(root,plan,descriptor,scene.finest_area(),kind,night,
                                                 native=True,opened=(scene,records)))
                    del scene; gc.collect()
            # Recheck RAM headroom each batch; CPU I/O can overlap one GPU job.
            completed=0; pages=[]
            with ThreadPoolExecutor(max_workers=4) as pool:
                batch=0
                while batch<len(jobs):
                    workers=page_workers()
                    futures=[pool.submit(write,root,metadata,c,r,index,utc) for c,r in jobs[batch:batch+workers]]
                    for future in futures:
                        pages.append(future.result()); completed+=1
                    batch+=len(futures)
                    update('native_global_pages',node=index,total=73,utc=utc,pages=completed,total_pages=len(jobs),page_workers=workers)
            node={'nominal_utc':utc,'index':index,'sources':[str(p) for p in metadata],
                  'pages':len(pages),'sun':sun_direction(utc_time(utc)).tolist()}
            save(root/f'reports/native_node_{index:04d}.json',node); nodes.append(node)
            if index==1:
                # Release science caches before the real all-page GPU render.
                gc.collect()
                from .gpu import release_idle
                release_idle()
                update('qualifying_first_native_globe',node=1,total=73,pages=len(jobs))
                from .first_globe import qualify
                qualify(root,blender,node,jobs,Path(sys.executable).with_name('EarthScience.Engine.exe'))
                source_bytes=sum((Path(p).parent/'geo_color.tif').stat().st_size for p in metadata)
                page_bytes=sum(Path(page['texture']).stat().st_size for page in pages)
                # Conservative forecast from a complete real native globe, not a proxy.
                forecast=int((source_bytes+page_bytes)*72*1.25)
                save(root/'reports/native_storage_forecast.json',{'first_node_source_bytes':source_bytes,
                     'first_node_page_bytes':page_bytes,'remaining_forecast_bytes':forecast,'nominal_nodes':73})
                check_disk(root,forecast)
        manifest={'nodes':nodes,'cells':jobs,'native_only':True,'proxy_textures':False,'global_native_precomputed':True,'frames':73,'hold':4,
                  'engine':str(Path(sys.executable).with_name('EarthScience.Engine.exe')),
                  'limits':'Original sensor measurements on a sphere; missing observations stay missing. Not 3D cloud reconstruction.'}
        save(output/'native_assets.json',manifest)
        from .gpu import release_idle
        release_idle()
        scripts=Path(__file__).resolve().parents[2]/'scripts'
        ready=output/'Earth_Native_73_UTC.blend'
        if not ready.exists():
            update('assembling_native_blender')
            with (root/'reports/native_blender_assemble.log').open('a',encoding='utf-8') as stream:
                subprocess.run([str(blender),'-b','--python-exit-code','1','--python',str(scripts/'blender_native_earth.py'),
                                '--','--root',str(root)],stdout=stream,stderr=subprocess.STDOUT,check=True)
        frames=output/'frames'; frames.mkdir(exist_ok=True)
        from .archive import sha
        identity=output/'render_scene_identity.json'; scene_sha=sha(ready)
        if identity.exists():
            if json.loads(identity.read_text(encoding='utf-8'))['scene_sha256']!=scene_sha:
                raise ValueError('Native scene changed after rendering began; previous renders preserved')
        else:
            save(identity,{'scene_sha256':scene_sha,'scene':str(ready),'frames':292,'native_only':True})
        missing=[str(f) for f in range(1,293) if not (frames/f'frame_{f:04d}.png').exists()]
        if missing:
            update('rendering_native_blender')
            with (root/'reports/native_blender_render.log').open('a',encoding='utf-8') as stream:
                subprocess.run([str(blender),'-b',str(ready),'--python-exit-code','1','--python',str(scripts/'blender_gpu_render.py'),
                                '-o',str(frames/'frame_'),'-F','PNG','-f',','.join(missing)],stdout=stream,stderr=subprocess.STDOUT,check=True)
        video=encode(output,292,1920,1080)
        save(output/'delivery_manifest.json',{'scene':str(ready),'scene_sha256':scene_sha,'video':str(video),
             'global_native_precomputed':True,'native_only':True,'proxy_images':False,'weather_nodes':73,
             'visual_acceptance_passed':False,'independent_coastline_acceptance_passed':False})
        update('native_ready_for_review',blend=str(ready),video=str(video),global_native_precomputed=True,
               visual_acceptance_passed=False,independent_coastline_acceptance_passed=False)
        return ready
    except Exception as error:
        update('native_failed',error=str(error)); raise
