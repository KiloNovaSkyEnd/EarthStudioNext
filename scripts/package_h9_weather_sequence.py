"""Package immutable native pages as Blender sequences, without L1 access."""
from pathlib import Path
from datetime import datetime,timedelta
import hashlib,json,os,sys
import numpy as np
import rasterio
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges.solar import sun_direction
from ges_next.isolation import require_writable
from ges.earth_validation.project import save

root=Path(__file__).resolve().parents[1]
project=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
out=require_writable(root/'data/exports/H9_20261020_12h_Blender_v1')
out.mkdir(exist_ok=True)
sequence=json.loads((project/'exports/weather_sequence.json').read_text())
assert len(sequence['frames'])==72
lookup={f['utc']:f for f in sequence['frames']}
base=json.loads(Path(sequence['frames'][0]['path']).read_text())
records=[];nodes=[];suns=[]
for index in range(73):
    utc=datetime.fromisoformat('2026-10-20T13:00:00+00:00')+timedelta(minutes=10*index)
    label=utc.isoformat().replace('+00:00','Z');frame=lookup.get(label)
    missing=frame is None
    assert not missing or label in sequence['missing_observations_utc']
    master=json.loads(Path(frame['path']).read_text()) if frame else base
    assert master['shape']==[22000,22000] and len(master['tiles'])==16
    for source_tile,reference in zip(master['tiles'],base['tiles']):
        assert all(source_tile[k]==reference[k] for k in ('path','shape','extent','transform','coreWindow'))
        target=out/'assets'/source_tile['path'].removesuffix('.tif')/f'weather_{index+1:04d}.tif'
        target.parent.mkdir(exist_ok=True,parents=True)
        if frame:
            source=Path(frame['path']).parent/source_tile['path']
            with source.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            assert checksum==source_tile['sha256']
            if not target.exists():os.link(source,target)
            with target.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==checksum
        else:
            if not target.exists():
                source=Path(sequence['frames'][0]['path']).parent/source_tile['path']
                with rasterio.open(source) as src:profile=src.profile
                profile.update(compress='DEFLATE',zlevel=1)
                with rasterio.open(target,'w',**profile) as dst:
                    for _,window in dst.block_windows(1):
                        dst.write(np.zeros((4,int(window.height),int(window.width)),dtype=np.uint8),window=window)
            with target.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        records.append(dict(path=target.relative_to(out).as_posix(),sha256=checksum,bytes=target.stat().st_size,missing=missing))
    nodes.append(dict(index=index+1,utc=label,hours_utc_minus7=6+index/6,missing=missing,
        scan_start=frame['scan_start'] if frame else None,scan_end=frame['scan_end'] if frame else None))
    suns.append(sun_direction(utc).tolist())
    print('PACKAGED_NATIVE_UTC',index+1,label,'missing' if missing else 'verified',flush=True)
save(out/'sequence_manifest.json',dict(schema='earthstudio.native_weather_sequence.v1',nodes=nodes,suns=suns,
    native_shape=[22000,22000],tiles=16,files=records,storage='Immutable NTFS hardlinks to owned native TIFFs; copy/move this entire delivery folder for portability. Never edit image files in place.',
    raw_L1_required=False,weather_interpolation=False,missing_policy='Transparent missing observation, neutral no-data display; no substitute scan'))
save(out/'native_master.json',base)
print('NATIVE_SEQUENCE_PACKAGED',out,flush=True)
