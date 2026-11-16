"""Precompute all display previews, prioritizing the user's currently slow scan."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,shutil,time,os
from ges_next.web_preview import prepare,compress_preview
from ges_next.isolation import require_writable

root=Path(__file__).resolve().parents[1];folder=require_writable(root/'data/cesium_h9_motion_20261020')
if shutil.disk_usage(folder).free<2*1024**3:raise RuntimeError('Need2GB free preview budget')
manifest_path=folder/'manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
frames=[f for f in manifest['frames'] if not f.get('missing')]
frames.sort(key=lambda f:(f['utc']!='2026-10-20T20:00:00Z',f['utc']))
started=time.perf_counter();rows=[]
def run(frame):
    master=folder/Path(frame['path']).parts[0]/'master.vrt';require_writable(master.parent)
    target,info=prepare(master)
    target,info=compress_preview(target,info)
    return frame,target,info
with ThreadPoolExecutor(max_workers=2) as pool:
    for future in as_completed([pool.submit(run,f) for f in frames]):
        frame,target,info=future.result()
        frame['previewPath']=target.relative_to(folder).as_posix();frame['previewBounds']=info['bounds']
        frame['previewSize']=[info['width'],info['height']]
        frame['limits']='H9 observed hemisphere only; precomputed4096 display preview; retained22000 native masters and RGB1km/IR2km source detail unchanged. Missing observations have no substituted weather.'
        temporary=manifest_path.with_suffix('.tmp');temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,manifest_path)
        rows.append(dict(utc=frame['utc'],**info));print(json.dumps(dict(done=len(rows),total=len(frames),utc=frame['utc'],seconds=round(info['seconds'],3),bytes=info['bytes'])),flush=True)
report=root/'reports/h9_web_bridge/fast_previews.json'
report.write_text(json.dumps(dict(frames=rows,elapsed_seconds=time.perf_counter()-started,missing_nodes=1,native_assets_unchanged=True),indent=2),encoding='utf-8')
print('ALL_NATIVE_DERIVED_WEB_PREVIEWS_READY',flush=True)
