"""One bounded H9 scan: real L1 -> stock layers -> primaryJPEG production assets."""
import gc
import json
import os
from pathlib import Path
import shutil
import time
from .assets import write_json, verify_assets
from .h9_source import decode, source_files
from .night_reference import reference_grid


def run(source_root, reference, utc, output, quality=95, night_metres=1000, keep_l1=False, keep_intermediates=False,
        input_files=None,night_reference=None,night_mode=None):
    from ges_next.isolation import require_writable
    output = require_writable(output)
    from ges_next.algorithms.night_modes import recipe as select_night
    selected_night=select_night({'NightMode':night_mode})
    optional_night=selected_night.mode!='geocolor'
    if optional_night:
        from .night_layers import preflight
        preflight(dict(NightMode=night_mode,NightLightMetres=night_metres))
    if night_metres not in (500,1000):raise ValueError('Night texture must be500m or1km')
    if type(quality) is not int or not 1 <= quality <= 100: raise ValueError('JPEG quality1..100 required')
    if (output/'commit.json').exists(): raise FileExistsError('Existing committed production package preserved')
    output.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output).free < 12*1024**3: raise ValueError('At least12GiB free space required for this bounded scan')
    began = time.monotonic()
    def report(phase, **details):
        value = dict(phase=phase, utc=utc, elapsed_seconds=round(time.monotonic()-began,2), **details)
        write_json(output/'status.json',value)
        print(json.dumps(value,ensure_ascii=False),flush=True)
    identity = dict(utc=utc, quality=quality, night_metres=night_metres, source_root=str(Path(source_root).resolve()), reference=str(Path(reference).resolve()))
    if optional_night:identity['night_recipe']=selected_night.identity()
    if input_files is not None: identity['input_files']=[str(Path(p).resolve()) for p in input_files]
    if night_reference is not None: identity['night_reference']=str(Path(night_reference).resolve())
    if (output/'job.json').exists() and json.loads((output/'job.json').read_text(encoding='utf-8')) != identity:
        raise ValueError('Job identity changed; choose a new output')
    from .journal import Journal
    journal=Journal(output.parent/'production_journal.sqlite')
    from .profile import h9_profile
    job=journal.create_job(output,h9_profile(quality,night_metres,night_mode),
        keep_l1=keep_l1,keep_intermediates=keep_intermediates,
        existing_readonly=(output/'job.json').exists())
    write_json(output/'job.json',identity)
    try:
        work=output/'work' if (output/'work').exists() else output/'scratch/work'
        work.mkdir(parents=True,exist_ok=True)
        from ges_next.performance.policy import settings
        performance=settings()
        configuration=dict(reserve_free_bytes=8*1024**3,compute_workers=performance['compute_workers'])
        write_json(output/'hardware_policy.json',performance)
        write_json(output/'project.json',configuration)
        write_json(work/'project.json',configuration)
        write_json(work.parent/'project.json',configuration)
        write_json(work.parent.parent/'project.json',configuration)
        report('verifying-and-decoding-inputs')
        selected=source_files(source_root,utc,input_files,bands=selected_night.bands if optional_night else None)
        files, inputs = decode(selected,work/'decoded')
        registrations=[]
        for source in selected:
            role='l1' if journal.job(job)['owned'] and source.resolve().is_relative_to(output/'raw') else 'reused'
            registrations.append((source,role))
            sidecar=Path(str(source)+'.json')
            if role=='l1' and sidecar.is_file():registrations.append((sidecar,'l1'))
        journal.register_inputs(job,utc,registrations)
        write_json(output/'inputs.json',dict(inputs=inputs,ownership='Only this job raw directory is owned; all other paths are read-only reused inputs'))
        from .rebuild_recipe import create as create_rebuild_recipe
        original_night=Path(night_reference) if night_reference else Path(source_root)/'raw/references/blackmarble_2016_500m/global_500m.vrt'
        rebuild_profile=dict(format='jpeg',disk_size=11000,quality=quality,night_metres=night_metres)
        if optional_night:rebuild_profile['NightMode']=night_mode
        rebuild=create_rebuild_recipe(output,utc,inputs,rebuild_profile,reference,night_reference=original_night)
        from ges.earth_validation import stock
        import satpy
        import yaml
        stock.configure(work)
        if quality==95 and night_metres==1000:
            # Same Satpy ndarray formula; share only equal same-scan angle
            # graphs/parameters/dtypes. Qualified by four exact asset hashes.
            config=Path(__file__).resolve().parents[2]/'ges/earth_validation'
            satpy.config.set(config_path=[str(config/'satpy_config'),str(config/'solar_satpy_config')])
        reference=Path(reference).resolve()
        runtime=work/'pyspectral_runtime.yaml'
        runtime.write_text(yaml.safe_dump(dict(download_from_internet=False,rayleigh_dir=str(reference/'pyspectral'),rsr_dir=str(reference/'pyspectral/rsr'))),encoding='utf-8')
        os.environ['PSP_CONFIG_FILE']=str(runtime)
        if performance['cuda_clouds']:
            try:
                from ges_next.performance.qualification import qualify
                qualify()
            except Exception:
                performance['cuda_clouds']=False
        os.environ['EARTHSTUDIO_H9_CUDA_CLOUDS']='1' if performance['cuda_clouds'] else '0'
        write_json(output/'hardware_policy.json',performance)
        satpy.config.set(data_dir=str(reference/'satpy_geocolor_v060'),download_aux=False)
        from .assets import digest
        shared=Path(__file__).resolve().parents[2]/('resources/cache/science-qualified-static-v1' if optional_night else 'resources/cache/science')/digest(original_night)
        shared.mkdir(parents=True,exist_ok=True)
        from .qualified_static import seed
        seed(shared)
        from ges_next.pipeline.locking import exclusive
        with exclusive(shared/'reference.lock',wait=True):
            night=reference_grid(original_night,shared/'night_1km.vrt',1000)
        from .static_night import reference_identity,StaticNight,materialize
        night_reference_id=reference_identity(original_night)
        write_json(work/'shared_cache.json',dict(path=str(shared),night_reference=night_reference_id,quality=quality))
        report('reading-h9-bands')
        scene=satpy.Scene(reader='ahi_hsd',filenames=[str(p) for p in files])
        scene.load(['B01','B02','B03','B04','B07','B13'])
        area=scene['B01'].attrs['area']
        if optional_night:
            from .qualified_static import assert_target_grid
            assert_target_grid(area,reference)
        from .h9_layers import store_layers
        capsule=work/'day_layers.json'
        binding=dict(utc=utc,inputs=[dict(name=Path(i['source']).name,bytes=i['bytes'],sha256=i['sha256']) for i in inputs],
            night_reference=night_reference_id,cloud_backend=bool(performance['cuda_clouds']),layers_code_sha256=digest(Path(__file__).with_name('h9_layers.py')))
        if optional_night and capsule.exists():
            import numpy as np
            cached_day=json.loads(capsule.read_text(encoding='utf-8'))
            if cached_day['binding']!=binding:raise ValueError('Stored day-layer source identity changed; inputs preserved')
            verify_assets(work,cached_day['arrays']);grid=cached_day['grid'];maps={}
            if grid['shape']!=list(area.shape) or grid['extent']!=list(area.area_extent) or grid['crs']!=area.crs.to_wkt():raise ValueError('Stored day grid differs from current source')
            for item in cached_day['arrays']:
                array=np.load(work/item['path'],mmap_mode='r+')
                if list(array.shape)!=item['array_shape'] or str(array.dtype)!=item['dtype']:raise ValueError('Stored day-array shape or dtype changed')
                maps[item['name']]=array
            report('reusing-verified-native-day-layers')
        else:
            maps, grid=store_layers(scene,area,night,reference,work,report,capture_night=optional_night)
            if optional_night:
                from .assets import record
                arrays=[dict(record(work,Path(value.filename),'owned-day-stage'),name=name,array_shape=list(value.shape),dtype=str(value.dtype)) for name,value in maps.items()]
                write_json(capsule,dict(binding=binding,grid=grid,arrays=arrays))
        del scene;gc.collect()
        report('encoding-jpeg-and-lossless-masks')
        from .jpeg_layers import encode_jpeg, encode_mask
        parity_night='assets/night.jpg' if night_metres==1000 else 'scratch/night_parity.jpg'
        slot=StaticNight(night_reference_id,grid,quality)
        cached,night_reused=slot.ensure(maps.get('night'))
        night_proof=None
        if optional_night:
            from .night_layers import apply
            night_proof=apply(maps,work,utc,selected,slot.path,night_mode,report)
            night_item=encode_jpeg(output,parity_night,maps['night_neutral'],quality,'shared-static-night-background',resume=True)
            night_item['sharing']='independent neutral-night derived reference'
        else:night_item=materialize(slot.path,output,parity_night,cached['asset'],link=night_metres==1000)
        write_json(output/'static_night.json',dict(key=slot.key,reused=night_reused,
            skipped_night_array='night' not in maps,sharing=night_item['sharing']))
        assets=[encode_jpeg(output,'assets/base.jpg',maps['base'],quality,'stock-clouds-day-without-ground-background',resume=True),
                night_item,
                encode_mask(output,'assets/transmission.png',maps['transmission'],'stock-ground-transmission',resume=True),
                encode_mask(output,'assets/support.png',maps['support'],'actual-observation-support',resume=True)]
        from .quality import measure
        quality_report=measure(output,maps['reference'],maps['support'],night_path=output/parity_night)
        if optional_night:quality_report['scope']='Full-grid candidate JPEG encoding fidelity; not stock GeoColor parity or measured-VIS accuracy'
        if night_metres==500:
            from .night_detail import asset,copy_asset,ROLE
            from pyresample.geometry import AreaDefinition
            actual_area=AreaDefinition('h9-cloud-grid','H9 cloud output','geos',grid['crs'],grid['shape'][1],grid['shape'][0],grid['extent'])
            cached,detail=asset(original_night,actual_area,quality,report)
            assets=[a for a in assets if a['role']!=ROLE]+[copy_asset(cached,output,detail)]
            grid.update(night_texture_metres=500,layer_shapes={ROLE:detail['asset']['shape']},night_reference_metres=500)
            quality_report.update(native_night_psnr_db=detail['psnr_db'],native_night_shape=detail['asset']['shape'],
                note='Cloud1km stock parity and actual500m ground JPEG checked independently; final mixed-resolution visual acceptance pending')
        write_json(output/'quality.json',quality_report)
        verify_assets(output,assets)
        for array in maps.values(): array.flush();array._mmap.close()
        del maps;gc.collect()
        if quality_report['psnr_db'] < 35: raise ValueError('JPEG numerical screening failed; inputs retained for review')
        from ges.solar import sun_direction
        from datetime import datetime
        commit=dict(schema='earthstudio.layered_jpeg.v1',utc=utc,grid=grid,assets=assets,rebuild_recipe=rebuild,quality=quality_report,
                    sun_ecef=sun_direction(datetime.fromisoformat(utc.replace('Z','+00:00'))).tolist(),
                    colour_encoding='sRGB encoded components; combine before applying sRGB EOTF',
                    controls=['groundEnabled','groundBrightness','groundHue','groundSaturation','groundTint'],
                    cleanup_eligible=False,visual_acceptance_pending=True,independent_blender_reopen_pending=True,
                    limitations=[f'One real H9 scan;1km clouds, {night_metres}m independent ground texture.','Static night includes terrain/city-light reference, not measured3D lamps.','Reused historicalL1 and originalTIFF/PNG never deleted.'])
        if optional_night:
            grid['formula']='displayRGB = approvedDayAndInferredNightBase + stockTransmission * neutralStaticNightRGB; then sRGB transfer'
            grid['base_interpretation']='Day: original Satpy branch. Night: AI-inferred VIS appearance from native IR, not observed VIS.'
            commit['night_recipe']=night_proof
            commit['limitations'].append('AI-estimated night appearance from native2km IR; 11K resampling adds no measured resolution.')
        write_json(output/'commit.json',commit)
        journal.submit(job,utc,output/'commit.json')
        if journal.job(job)['owned']:
            registrations=[]
            if night_metres==500:
                registrations.append((output/parity_night,'temporary'))
            for temporary in sorted(work.rglob('*')):
                if temporary.is_file() and '.part' not in temporary.name:
                    registrations.append((temporary,'temporary'))
            journal.register_inputs(job,utc,registrations)
        report('committed-awaiting-blender-verification',asset_bytes=sum(a['bytes'] for a in assets),quality=quality_report)
        return commit
    except Exception as error:
        report('failed-inputs-preserved',error=str(error))
        raise
    finally:
        journal.close()
