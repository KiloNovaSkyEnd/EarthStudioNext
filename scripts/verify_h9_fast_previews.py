"""Verify complete, display-only sequence and original-source fingerprints."""
from pathlib import Path
import json,os
from PIL import Image
from ges_next.preview_server import native_signature

root=Path(__file__).resolve().parents[1];folder=root/'data/cesium_h9_motion_20261020';path=folder/'manifest.json'
manifest=json.loads(path.read_text(encoding='utf-8'));observed=[f for f in manifest['frames'] if not f.get('missing')]
assert len(observed)==72 and len(manifest['frames'])==73
rows=[]
for frame in observed:
    image=folder/frame['previewPath'];info=json.loads(image.with_suffix('.json').read_text(encoding='utf-8'))
    assert image.stat().st_size==info['bytes']
    assert info['native_signature']==native_signature(image.parent/'master.vrt')
    with Image.open(image) as png:
        assert png.size==(4096,2048) and png.mode=='RGBA';png.verify()
    frame['limits']='H9 observed hemisphere only; precomputed4096 display preview; retained22000 native masters and RGB1km/IR2km source detail unchanged. Missing observations have no substituted weather.'
    rows.append(dict(utc=frame['utc'],path=frame['previewPath'],bytes=info['bytes']))
gap=next(f for f in manifest['frames'] if f.get('missing'));assert gap['utc']=='2026-10-20T14:40:00Z' and 'previewPath' not in gap
temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,path)
report=dict(prepared_frames=72,nominal_nodes=73,preview_dimensions=[4096,2048],display_only=True,
            total_preview_bytes=sum(r['bytes'] for r in rows),all_preview_images_verified=True,
            all_native_source_fingerprints_unchanged=True,missing_node_has_no_substitute=True,frames=rows)
(root/'reports/h9_web_bridge/fast_previews_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('ALL72_DISPLAY_PREVIEWS_VERIFIED',report['total_preview_bytes'],flush=True)
