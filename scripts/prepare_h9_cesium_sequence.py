"""Bind read-only committed H9 native masters to the local Cesium preview."""
from pathlib import Path
from datetime import datetime,timedelta
import json,os,shutil,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable
from ges.earth_validation.project import save
root=Path(__file__).resolve().parents[1]
project=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
out=require_writable(root/'data/cesium_h9_motion_20261020');out.mkdir(exist_ok=True)
sequence=json.loads((project/'exports/weather_sequence.json').read_text())
frames=[];lookup={f['utc']:f for f in sequence['frames']}
assert len(lookup)==72
for i in range(73):
    stamp=datetime.fromisoformat('2026-10-20T13:00:00+00:00')+timedelta(minutes=10*i)
    utc=stamp.isoformat().replace('+00:00','Z');source=lookup.get(utc)
    missing=source is None;assert not missing or utc in sequence['missing_observations_utc']
    frame=dict(utc=utc,label=f'{6+i//6:02}:{i%6*10:02} UTC−7 · '+utc+(' · 缺档' if missing else ''),
        source='Himawari-9 / AHI',recipe='Satpy0.60 stock GeoColor / 500m static night input',
        detail='native-product',bounds=[-180,-85,180,85],missing=missing,
        limits='H9 observed hemisphere only; geographic preview derived on demand from retained22000 grid; RGB1km/IR2km. Missing observations have no substituted weather.')
    if source:
        folder=out/stamp.strftime('%Y%m%dT%H%MZ');folder.mkdir(exist_ok=True)
        native=Path(source['path']).parent
        for path in native.glob('native_*.tif'):
            target=folder/path.name
            if not target.exists():os.link(path,target)
        for name in ['master.vrt','manifest.json']:shutil.copy2(native/name,folder/name)
        frame.update(kind='geographic-tiles',path=folder.name+'/tiles/{z}/{x}/{y}.png',maximumLevel=8,tileSize=512,
            scanStartUtc=source['scan_start'],scanEndUtc=source['scan_end'])
    else:frame.update(kind='single-image',path='no-observation.png')
    frames.append(frame)
shutil.copy2(root/'native/EarthStudio.App/Cesium/no-observation.png',out/'no-observation.png')
save(out/'manifest.json',dict(schema='earthstudio.materials.v1',earthModel='WGS84',scope='regional',
    frames=frames,defaultView=dict(targetLon=130.7,targetLat=18,heading=0,pitch=-45,rangeKm=4500,roll=0,fov=40),
    missingObservationsUtc=sequence['missing_observations_utc'],observedFrames=72))
print('CESIUM_12H_NATIVE_SEQUENCE_READY',out,flush=True)
