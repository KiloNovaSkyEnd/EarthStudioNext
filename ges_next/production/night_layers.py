"""Optional pinned AI night stages inside a per-scan owned work directory."""
import fnmatch,json,os,subprocess,sys
from pathlib import Path
import numpy as np
from PIL import Image
from ges_next.algorithms.night_modes import recipe,compose,neutral_ground_background
Image.MAX_IMAGE_PIXELS=500_000_000

def gpu_python():
    root=Path(__file__).resolve().parents[2]
    configured=os.environ.get('EARTHSTUDIO_AIVIS_PYTHON')
    if configured:return Path(configured)
    bundled=root/'Runtime/GpuSlot/GpuSlot.exe'
    if bundled.is_file():
        if not (root/'Runtime/AI/python.exe').is_file():
            raise ValueError('请将 AI-VIS 运行时资源包解压到软件目录。')
        return bundled
    config=root/'resources/models/aivis/runtime.json'
    if not config.exists():raise ValueError('AI-VIS运行环境未配置；不能回退为GeoColor')
    return Path(json.loads(config.read_text(encoding='utf-8'))['python'])

def preflight(profile):
    selected=recipe(profile)
    if selected.mode=='geocolor':return
    if profile.get('NightLightMetres',1000)!=1000:raise ValueError('新增夜间模式的500m独立夜景尚待资格验证；请选择1km夜景或默认GeoColor')
    from .assets import digest
    root=Path(__file__).resolve().parents[2]
    weight=root/'resources/models/aivis/aivis_setup/weights/aivis_1_0.safetensors'
    if not gpu_python().is_file() or not weight.is_file() or digest(weight)!=selected.weights_sha256:raise ValueError('AI-VIS运行环境或模型指纹不匹配')

def apply(maps,work,utc,sources,static_night,night_mode,report):
    from ges_next.algorithms.aivis import calibrate,render_pure,render_v9
    work=Path(work);selected=recipe({'NightMode':night_mode})
    from ges_next.algorithms.aivis.demand import configure
    demand_route=configure(work,utc,night_mode)
    report('night-demand-route',**demand_route)
    import gc
    retained={name:Path(value.filename) for name,value in maps.items()}
    for value in maps.values():value.flush();value._mmap.close()
    maps.clear();gc.collect()
    class Inputs:
        def glob(self,pattern):return [Path(p) for p in sources if fnmatch.fnmatch(Path(p).name,pattern)]
    calibration=work/'full_disk_arrays/calibration.json'
    complete=json.loads(calibration.read_text(encoding='utf-8')).get('complete') is True if calibration.exists() else False
    if not complete:
        report('calibrating-additional-ir')
        calibrate.ROOT=work;calibrate.RAW_DIR=Inputs();calibrate.UTC=utc;calibrate.main()
    if not (work/'full_disk_ai_tiled_gpu.json').exists():
        report('inferring-ai-night')
        with (work/'ai_inference.log').open('a',encoding='utf-8') as log:
            subprocess.run([str(gpu_python()),'-m','ges_next.algorithms.aivis.runtime','--work',str(work),'--utc',utc],cwd=Path(__file__).resolve().parents[2],stdout=log,stderr=subprocess.STDOUT,check=True)
    render=render_pure if night_mode=='ai-vis' else render_v9
    appearance=work/('full_disk_pure_ai_vis_11000.jpg' if night_mode=='ai-vis' else 'full_disk_v9_11000.jpg')
    if not appearance.exists():
        report('rendering-night-appearance');render.ROOT=work;render.UTC=utc
        if hasattr(render,'DIR'):render.DIR=work/'full_disk_arrays'
        render.main()
    for name,path in retained.items():maps[name]=np.load(path,mmap_mode='r+')
    for name in ('base','reference'):
        maps[name]._mmap.close()
        maps[name]=np.lib.format.open_memmap(work/('candidate_'+name+'.npy'),mode='w+',dtype='u1',shape=(11000,11000,3))
    from .neutral_night import enabled_for, ground as cached_ground
    neutral_cache_enabled=enabled_for(work,utc,night_mode)
    if neutral_cache_enabled:
        report('reusing-neutral-reference')
        ground=cached_ground(static_night,work)
    else:
        ground=np.lib.format.open_memmap(work/'night_neutral.npy',mode='w+',dtype='u1',shape=(11000,11000,3))
        with Image.open(static_night) as image:
            if image.size!=(11000,11000):raise ValueError('Optional night source grid differs')
            image.load()
            for y in range(0,11000,250):
                stop=min(y+250,11000);rgb=np.asarray(image.crop((0,y,11000,stop)),np.float32)/255
                ground[y:stop]=np.uint8(np.rint(np.clip(neutral_ground_background(rgb),0,1)*255))
    max_day_error=0;full_day_count=0
    with Image.open(appearance) as image:
        if image.size!=(11000,11000):raise ValueError('Night appearance grid differs')
        image.load()
        for y in range(0,11000,250):
            sl=slice(y,min(y+250,11000))
            night=np.asarray(image.crop((0,y,11000,sl.stop)),np.float32)/255
            day=np.asarray(maps['day_branch'][sl],np.float32)/255
            solar=np.asarray(maps['solar_branch'][sl],np.float32)/65535
            cloud=1-(1-np.asarray(maps['high_branch'][sl],np.float32)/255)*(1-np.asarray(maps['low_branch'][sl],np.float32)/255)
            valid=maps['support'][sl]>0
            maps['base'][sl]=np.uint8(np.rint(compose(day,night,solar,cloud,valid,night_mode)*255))
            full=(maps['solar_branch'][sl]==65535)&valid;full_day_count+=int(full.sum())
            if full.any():max_day_error=max(max_day_error,int(np.abs(maps['base'][sl][full].astype('i2')-maps['day_branch'][sl][full].astype('i2')).max()))
            reconstructed=np.asarray(maps['base'][sl],np.float32)/255+np.asarray(ground[sl],np.float32)/255*(np.asarray(maps['transmission'][sl],np.float32)/65535)[...,None]
            maps['reference'][sl]=np.uint8(np.rint(np.clip(reconstructed,0,1)*255))
    if max_day_error:raise ValueError('Optional mode changed full-day pixels')
    maps['night_neutral']=ground
    from .assets import write_json
    proof=dict(utc=utc,recipe=selected.identity(),day_full_weight_pixels=full_day_count,max_day_branch_difference_dn=max_day_error,
        encoding_reference='Candidate composite before final JPEG; not stock GeoColor or observed-VIS truth')
    proof['execution']=dict(demand_route)
    proof['execution']['neutral_reference_cache']=neutral_cache_enabled
    if demand_route['enabled']:
        inference=json.loads((work/'full_disk_ai_tiled_gpu.json').read_text(encoding='utf-8'))
        proof['execution'].update({k:inference[k] for k in ('tiles_selected','tiles_inferred','demand_limited','execution_revision') if k in inference})
    write_json(work.parent.parent/'night_recipe.json',proof)
    report('optional-night-composed',day_full_weight_pixels=full_day_count)
    return proof
