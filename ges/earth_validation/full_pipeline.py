"""Persistent local production chain; no chat interaction required between stages."""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import traceback
from .project import save,check_disk
from .sequence_job import run as sequence
from .blender_assets import prepare_sequence
from .camera_tiles import process
from .video_check import encode


def run(root,blender):
    import msvcrt
    root=Path(root).resolve()
    with (root/'reports/full_pipeline.lock').open('a+b') as lock:
        if lock.tell()==0: lock.write(b'0'); lock.flush()
        lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        import ctypes
        # Keep this workstation awake only while this authorized job runs;
        # releasing/resetting the thread restores the previous power policy.
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        try: return _run(root,blender)
        finally: ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


def _run(root,blender):
    root=Path(root).resolve(); blender=Path(blender).resolve()
    if not blender.is_file(): raise FileNotFoundError('Blender executable missing')
    scripts=Path(__file__).resolve().parents[2]/'scripts'
    state=root/'reports/full_pipeline_status.json'
    output=root/'exports/earth_camera_sequence_v1'; output.mkdir(parents=True,exist_ok=True)
    def update(stage,**values):
        save(state,{'stage':stage,'updated_utc':datetime.now(timezone.utc).isoformat(),**values})
        print(stage,values,flush=True)
    def call(arguments,label):
        log=root/'reports'/f'full_{label}.log'
        offset=log.stat().st_size if log.exists() else 0
        with log.open('a',encoding='utf-8') as stream:
            subprocess.run([str(blender),'-b',*arguments],stdout=stream,stderr=subprocess.STDOUT,check=True)
        with log.open('rb') as stream:
            stream.seek(offset); text=stream.read().decode('utf-8',errors='replace')
        if 'Failed to load' in text or 'Loading weather_0000.png' in text: raise RuntimeError('Blender texture loading failed')
    try:
        check_disk(root,250_000_000_000)
        update('complete_observation_sequence')
        from .sequence_resume import verify
        if not verify(root): sequence(root)
        engine=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-X','utf8','-m','ges.earth_validation']
        prepare_sequence(root,engine,Path(__file__).resolve().parents[2])
        base=output/'Earth_20220831_73_UTC.blend'; ready=output/'Earth_20220831_Camera_Ready.blend'
        if not base.is_file():
            update('building_editable_scene')
            call(['--python-exit-code','1','--python',str(scripts/'blender_stock_validation.py'),
                  '--','--root',str(root),'--sequence'],'build')
        request_record=root/'reports/sequence_camera_request.json'
        if not request_record.is_file():
            update('measuring_camera_footprint')
            call([str(base),'--python-exit-code','1','--python',str(scripts/'blender_sequence_tasks.py'),
                  '--','--root',str(root),'--stage','request'],'request')
        request=Path(json.loads(request_record.read_text(encoding='utf-8'))['request'])
        if not ready.is_file():
            update('preparing_camera_original_detail',request=str(request))
            result=process(root,request)
            update('assembling_camera_scene')
            call([str(base),'--python-exit-code','1','--python',str(scripts/'blender_sequence_tasks.py'),
                  '--','--root',str(root),'--stage','assemble','--result',str(result)],'assemble')
        frames=output/'frames'; frames.mkdir(exist_ok=True)
        from .archive import sha
        identity=output/'render_scene_identity.json'
        scene_sha=sha(ready)
        if identity.is_file():
            previous=json.loads(identity.read_text(encoding='utf-8'))
            if previous['scene_sha256']!=scene_sha:
                raise ValueError('The scene was edited after rendering began. Existing renders are preserved; use a new export version.')
        else: save(identity,{'scene':str(ready),'scene_sha256':scene_sha,'frames':292,'shape':[1080,1920]})
        missing=[f for f in range(1,293) if not (frames/f'frame_{f:04d}.png').is_file()]
        if missing:
            update('rendering_verification_video',frames=len(missing))
            call([str(ready),'--python-exit-code','1','--python',str(scripts/'blender_gpu_render.py'),
                  '-o',str(frames/'frame_'),'-F','PNG','-f',','.join(map(str,missing))],'render')
        update('decoding_verification_video')
        video=encode(output,292,1920,1080)
        save(output/'delivery_manifest.json',{'scene':str(ready),'scene_sha256':scene_sha,'video':str(video),
            'weather_nodes':73,'render_frames':292,'camera_detail_request':str(request),
            'ready_for_camera_editing':True,'new_views_require_matching_detail_preparation':True,
            'global_native_precomputed':False,'independent_coastline_acceptance_passed':False,
            'visual_acceptance_passed':False})
        update('ready_for_user_review',blend=str(ready),video=str(video),weather_nodes=73,
               prepared_for_this_camera=True,global_native_precomputed=False,visual_acceptance_passed=False)
        (output/'READY.txt').write_text('Blender scene: '+str(ready)+'\nVideo: '+str(video)+
            '\n73 real nominal time nodes. Original detail is prepared for the supplied camera.\n'
            'New viewpoints/resolution: use Satellite Earth addon to prepare matching original pixels.\n'
            'This is imagery on a sphere, not reconstructed 3D cloud volume. SEVIRI is observed natural colour.\n',encoding='utf-8')
        return ready
    except Exception as error:
        update('failed',error_type=type(error).__name__,error=str(error)); traceback.print_exc(); raise
