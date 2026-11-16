"""Bounded real first-sample test, read-only archived L1; never accepts quality or cleans."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.pipeline.plan import create
from ges_next.pipeline.runner import run
from ges_next.pipeline.workers import Workers
from ges_next.production.assets import write_json


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'data/pipeline_acceptance/H9_cached_first_sample_M4_r2'
    cache=root/'data/projects/H9_20261020_UTCminus7_1100_1700'
    project=dict(Id='a46cff67-1903-43c8-b67b-e0d152811b5b',StartUtc='2026-10-20T13:00:00Z',EndUtc='2026-10-20T13:10:00Z',IntervalMinutes=10,
        SatelliteSelection=dict(Mode='manual',Preset='h9',Satellites=['himawari9']),
        Production=dict(Format='jpeg',HimawariDiskSize=11000,NightLightMetres=1000,JpegQuality=95,KeepL1=False,KeepIntermediates=False))
    if not (output/'plan.json').exists():
        records=[]
        for minute in ('00','10'):
            files=sorted((cache/f'raw/20261020T13{minute}Z').glob('*.bz2'))
            receipts=[json.loads(Path(str(p)+'.json').read_text(encoding='utf-8')) for p in files]
            utc=f'2026-10-20T13:{minute}:00Z'
            records.append(dict(requested_utc=utc,source='himawari9',state='available',native=dict(satellite='himawari9',observed_utc=utc,
                bucket='noaa-himawari9',keys=[r['key'] for r in receipts],sizes=[r['bytes'] for r in receipts],etags=[r['etag'] for r in receipts])))
        inventory=root/'reports/native_pipeline_m4/cached_inventory.json'
        write_json(inventory,dict(project_id=project['Id'],finished=True,project_spec=project,records=records,
            provenance='Existing local authoritative download receipts; not a fresh provider catalog query.'))
        create(project,inventory,output)
        write_json(output/'validation_project.earthproj',project)
    class NoNetwork:
        def get_object(self,**kwargs):raise RuntimeError('Bounded test forbids new payloads; expected verified historical cache')
    def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
    workers=Workers(root.parent/'GlobalSatelliteEarthStudio/data/raw/reference',cache/'raw/references/blackmarble_2016_500m/global_500m.vrt',
        cache,'D:/Softwares/Blender/blender.exe',emit)
    state=run(output,NoNetwork(),workers,cache,False,emit)
    if state['phase']!='awaiting-quality':raise RuntimeError('Expected real first-sample checkpoint')
    if len(list((output/'steps').glob('*/commit.json')))!=1:raise RuntimeError('Bounded test processed more than one scan')


if __name__=='__main__':main()
