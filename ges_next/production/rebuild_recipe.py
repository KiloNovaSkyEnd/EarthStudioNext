"""Small persistent recipe for reacquiring one exact H9 scan, without retaining L1."""
from datetime import datetime,timedelta
import importlib.metadata
import json
from pathlib import Path
import re
from .assets import write_json,digest,record

BANDS=('B01','B02','B03','B04','B07','B13')


def validate(recipe):
    if recipe.get('schema')!='earthstudio.h9.rebuild.v1': raise ValueError('Unsupported rebuild recipe')
    when=datetime.fromisoformat(recipe['utc'].replace('Z','+00:00'))
    if when.utcoffset()!=timedelta(0) or when.second or when.microsecond or when.minute%10: raise ValueError('Exact UTC scan required')
    from ges_next.algorithms.night_modes import recipe as night_recipe
    selected=night_recipe(recipe.get('profile',{}))
    bands=selected.bands if selected.mode!='geocolor' else BANDS
    if selected.mode!='geocolor' and recipe.get('night_recipe')!=selected.identity():raise ValueError('Optional night recipe identity differs')
    expected={(band,segment) for band in bands for segment in range(1,11)};seen=set()
    prefix=when.strftime('AHI-L1b-FLDK/%Y/%m/%d/%H%M/')
    for item in recipe['inputs']:
        name=item['key'].removeprefix(prefix)
        match=re.fullmatch(rf'HS_H09_{when:%Y%m%d_%H%M}_(B\d\d)_FLDK_R\d\d_S(\d\d)10\.DAT\.bz2',name)
        if not item['key'].startswith(prefix) or not match: raise ValueError('Rebuild source belongs to another scan')
        identity=(match[1],int(match[2]))
        if identity in seen: raise ValueError('Duplicate rebuild input')
        seen.add(identity)
        if item['bucket']!='noaa-himawari9' or type(item['bytes']) is not int or item['bytes']<=0: raise ValueError('Invalid rebuild source')
        if not re.fullmatch('[0-9a-f]{64}',item['sha256']) or not item.get('etag'): raise ValueError('Unpinned rebuild source')
    if seen!=expected or len(recipe['inputs'])!=len(expected): raise ValueError('Complete selected-band H9 scan required')
    return when


def create(root,utc,inputs,profile,reference,night_reference=None):
    rows=[]
    for item in inputs:
        source=Path(item['source'])
        receipt=json.loads(Path(str(source)+'.json').read_text(encoding='utf-8'))
        if receipt.get('source')!='NOAA anonymous S3 Himawari9': raise ValueError('No verified H9 provider receipt')
        if receipt['bytes']!=item['bytes'] or receipt['sha256']!=item['sha256']: raise ValueError('Provider receipt differs from decoded input')
        rows.append(dict(bucket='noaa-himawari9',key=receipt['key'],bytes=item['bytes'],etag=receipt['etag'],sha256=item['sha256']))
    modules=['satpy','numpy','dask','pyresample','pyspectral','Pillow']
    code=Path(__file__).resolve().parent
    recipe=dict(schema='earthstudio.h9.rebuild.v1',utc=utc,satellite='himawari9',inputs=rows,profile=profile,
        versions={name:importlib.metadata.version(name) for name in modules},
        scientific_code_sha256={name:digest(code/name) for name in ['h9_layers.py','h9_job.py','night_reference.py','night_detail.py']},
        auxiliary_reference_root=str(Path(reference).resolve()),
        limitations=['Reacquisition requires provider archive availability and matching pinned bytes.',
                     'Exact recomputation also requires the recorded scientific environment and shared auxiliary references.',
                     'Rebuild to a new candidate package; never overwrite the accepted sequence automatically.'])
    if night_reference is not None:
        night_reference=Path(night_reference).resolve()
        manifest=night_reference.parent/'manifest.json'
        recipe['night_reference']=dict(path=str(night_reference),vrt_sha256=digest(night_reference),
            manifest_sha256=digest(manifest) if manifest.exists() else None)
    from ges_next.algorithms.night_modes import recipe as night_recipe
    selected=night_recipe(profile)
    if selected.mode!='geocolor':recipe['night_recipe']=selected.identity()
    validate(recipe)
    target=Path(root)/'rebuild_recipe.json';write_json(target,recipe)
    return record(root,target,'single-scan-rebuild-recipe')
