"""Independent reopen verifies unchanged native editing state and updated weather files."""
import json,sys,hashlib
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.production.assets import verify_assets
from scripts.blender_support.artist_state import snapshot

root=Path(bpy.data.filepath).parent
receipt=json.loads((root/'artist_update.json').read_text(encoding='utf-8'))
if receipt['before']!=receipt['after'] or snapshot()!=receipt['before']:raise ValueError('Artist native editing state changed after reopen')
sequence=json.loads((root/'sequence_manifest.json').read_text(encoding='utf-8'))
verify_assets(root,sequence['files']+sequence['auxiliary_files'])
entries={(root/a['path']).resolve():a for a in sequence['files']+sequence['auxiliary_files'] if a.get('shape')}
decoded=[]
for image in bpy.data.images:
    if image.source not in ('FILE','SEQUENCE'):continue
    path=Path(bpy.path.abspath(image.filepath)).resolve()
    if path not in entries:continue
    # Shared SEQUENCE datablocks may reference an unevaluated frame in another
    # scene. Decode the exact committed FILE independently without editing that state.
    probe=bpy.data.images.load(str(path),check_existing=False)
    if list(probe.size)[::-1]!=entries[path]['shape']:raise ValueError('Updated weather decode shape differs: '+str(path))
    probe.pixels[0];decoded.append(str(path));bpy.data.images.remove(probe)
if not decoded:raise ValueError('Updated weather not linked')
proof=dict(schema='earthstudio.artist_update.reopen.v1',edits_preserved=True,weather_decoded=len(decoded),
    blend_sha256=hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest())
(root/'artist_reopen.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
print('ARTIST_UPDATE_REOPEN_VERIFIED',json.dumps(proof),flush=True)
