"""Compress already prepared display images; never decode original TIFFs."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,os,time
from ges_next.web_preview import compress_preview
root=Path(__file__).resolve().parents[1];folder=root/'data/cesium_h9_motion_20261020'
path=folder/'manifest.json';manifest=json.loads(path.read_text(encoding='utf-8'));frames=[f for f in manifest['frames'] if not f.get('missing')]
started=time.perf_counter();rows=[]
def run(frame):
    image=folder/frame['previewPath'];info=json.loads(image.with_suffix('.json').read_text(encoding='utf-8'))
    if image.suffix=='.webp':return frame,image,info
    target,metadata=compress_preview(image,info);return frame,target,metadata
with ThreadPoolExecutor(max_workers=2) as pool:
    for future in as_completed([pool.submit(run,f) for f in frames]):
        frame,target,info=future.result();frame['previewPath']=target.relative_to(folder).as_posix()
        rows.append(dict(utc=frame['utc'],bytes=info['bytes']));print('COMPRESSED',len(rows),len(frames),frame['utc'],info['bytes'],flush=True)
temp=path.with_suffix('.tmp');temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)
(root/'reports/h9_web_bridge/fast_preview_compression.json').write_text(json.dumps(dict(frames=rows,total_bytes=sum(r['bytes'] for r in rows),elapsed_seconds=time.perf_counter()-started,display_only=True),indent=2),encoding='utf-8')
print('ALL72_WEB_TEXTURES_READY',flush=True)
