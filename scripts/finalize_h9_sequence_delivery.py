"""Seal the reviewed editable H9 weather package after actual Blender checks."""
import hashlib,json,shutil,sys
from pathlib import Path
from datetime import datetime,timezone
import imageio_ffmpeg
from PIL import Image
root=Path(__file__).resolve().parents[1]
out=root/'data/exports/H9_20261020_12h_Blender_v1'
seal=out/'delivery_checksums.json'
if seal.exists():raise FileExistsError('Finalized delivery preserved')
proof=root/'reports/h9_sequence_delivery'
structure=json.loads((proof/'final/verification.json').read_text())
cameras=json.loads((proof/'final_cameras.json').read_text())
user=json.loads((proof/'user_take.json').read_text())
portable=json.loads((proof/'final_portable/portability.json').read_text())
assert len(structure['scenes'])==6 and len(cameras)==5
assert user['native_keying_operator_executed_twice'] and user['actual_custom_keyframe_poses_rendered']==[1,451,901]
assert all(c['retime_2x_preserves_camera_and_weather'] for c in cameras)
assert portable['relative_native_sequences']==16 and portable['all1168_images_present']
manifest=json.loads((out/'sequence_manifest.json').read_text())
assert len(manifest['files'])==1168 and sum(n['missing'] for n in manifest['nodes'])==1
for index,record in enumerate(manifest['files']):
    path=out/record['path'];assert path.stat().st_size==record['bytes']
    with path.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==record['sha256']
    if index%160==0:print('SEAL_NATIVE_FILE',index,flush=True)
reader=imageio_ffmpeg.read_frames(str(out/'天气与运镜验收预览.mp4'),pix_fmt='rgb24')
video=next(reader);frames=sum(1 for _ in reader)
assert frames==73 and video['size']==(640,360) and video['fps']==12
assert Image.open(out/'4K原生素材检查.png').size==(3840,2160)
verification=out/'verification';verification.mkdir(exist_ok=True)
for source,name in [(proof/'final/verification.json','weather_and_scenes.json'),(proof/'final_cameras.json','cameras_sun_retime.json'),
                    (proof/'user_take.json','record_two_camera_poses.json'),(proof/'final_portable/portability.json','portability.json')]:
    shutil.copy2(source,verification/name)
for folder in ['final','user_take_frames','final_portable']:
    destination=verification/folder;destination.mkdir(exist_ok=True)
    for path in (proof/folder).glob('*.png'):shutil.copy2(path,destination/path.name)
(verification/'preview_video.json').write_text(json.dumps(dict(decoded_frames=frames,fps=12,size=[640,360],duration_seconds=73/12,
    genuine_observations=72,explicit_missing_nodes=1,preview_only=True),indent=2),encoding='utf-8')
summary=dict(schema='earthstudio.editable_h9_weather_delivery.v1',verified_utc=datetime.now(timezone.utc).isoformat(),
    project='Earth_Studio_动态天气与自由运镜.blend',independent_takes=6,example_takes=5,clean_user_take=1,
    weather_nodes=73,genuine_observations=72,missing_utc=['2026-10-20T14:40:00Z'],native_shape=[22000,22000],
    camera_samples_verified=sum(c['samples'] for c in cameras),weather_clock_nodes_verified=6*73,
    all_native_asset_hashes_verified=True,standalone_relocated_blender_rendered=True,
    preview_frames=73,final_quality_4k_still=True,raw_L1_deleted=False,
    acceptance='Ready for user visual/workflow acceptance; no claim of complete desktop/Cesium product or automatic L1 cleanup')
(out/'delivery_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
records=[]
for path in sorted(out.rglob('*')):
    if not path.is_file():continue
    if path.is_relative_to(out/'assets'):
        source=next(r for r in manifest['files'] if r['path']==path.relative_to(out).as_posix());checksum=source['sha256']
    else:
        with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    records.append(dict(path=path.relative_to(out).as_posix(),bytes=path.stat().st_size,sha256=checksum))
seal.write_text(json.dumps(dict(project=summary['project'],files=records),ensure_ascii=False,indent=2),encoding='utf-8')
print('EDITABLE_H9_DELIVERY_SEALED',json.dumps(summary,ensure_ascii=False),flush=True)
