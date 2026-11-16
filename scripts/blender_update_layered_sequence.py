"""Save an updated copy; never overwrite an artist's source .blend."""
import json,sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from scripts.blender_support.update_weather import update
from scripts.blender_support.artist_state import snapshot

args=sys.argv[sys.argv.index('--')+1:];root=Path(args[0]).resolve()
target=require_writable(root/'EarthStudio_保留编辑_更新天气.blend')
if target.exists():raise FileExistsError('Existing updated artist file preserved')
source=Path(bpy.data.filepath).resolve()
if source==target:raise ValueError('Artist source cannot be overwritten')
before=snapshot()
from scripts.blender_support.dual_airglow import upgrade_all
airglow_scenes=upgrade_all()
scenes=update(root)
after=snapshot()
if before!=after:raise ValueError('Artist camera/action/effect/render state changed; updated file not saved')
# New weather images become portable; unrelated artist dependencies keep their resolved paths.
for image in bpy.data.images:
    if image.source not in ('FILE','MOVIE','SEQUENCE'):continue
    path=Path(bpy.path.abspath(image.filepath)).resolve()
    image.filepath='//'+path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
bpy.ops.wm.save_as_mainfile(filepath=str(target),relative_remap=False)
(root/'artist_update.json').write_text(json.dumps(dict(source=str(source),target=str(target),scenes=scenes,
    independent_airglow_upgraded=airglow_scenes,existing_animation_preserved=True,weather_curves_extended=False,before=before,after=after),ensure_ascii=False,indent=2),encoding='utf-8')
print('ARTIST_WEATHER_UPDATE_READY',target,flush=True)
