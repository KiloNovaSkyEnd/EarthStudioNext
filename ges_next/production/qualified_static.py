"""Install the accepted immutable H9 land/water reference into a separate cache namespace."""
from pathlib import Path
import json,shutil
from .assets import digest
ROOT=Path(__file__).resolve().parents[2]
MANIFEST_SHA256='081a1710907189e7206a8cdf53c322a7012cafd1d040bb8093b5b05bb877d486'
def seed(shared):
    folder=ROOT/'resources/references/qualified_h9_landmask_v1'
    if digest(folder/'manifest.json')!=MANIFEST_SHA256:raise ValueError('Qualified static mask manifest changed')
    data=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    target=Path(shared)/'static_landmask_grids_v1';target.mkdir(parents=True,exist_ok=True)
    for item in data['files']:
        source=folder/item['path'];dest=target/item['path']
        if digest(source)!=item['sha256']:raise ValueError('Qualified static mask source changed')
        if dest.exists():
            if digest(dest)!=item['sha256']:raise ValueError('Conflicting static mask cache preserved; choose a fresh cache namespace')
        else:
            part=dest.with_suffix(dest.suffix+'.part');shutil.copyfile(source,part);part.replace(dest)
    return MANIFEST_SHA256


def assert_target_grid(area,reference):
    """A pinned grid may not silently stand in for a different navigation/reference."""
    folder=ROOT/'resources/references/qualified_h9_landmask_v1'
    data=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    receipt=next(item for item in data['files'] if item['path'].endswith('.json'))
    source=folder/receipt['path']
    if digest(source)!=receipt['sha256']:raise ValueError('Qualified grid receipt changed')
    identity=json.loads(source.read_text(encoding='utf-8'))['identity']
    actual=[area.crs.to_wkt(),list(area.shape),list(area.area_extent)]
    if actual!=identity['target_grid']:raise ValueError('AI night navigation differs from accepted static reference; inputs preserved')
    mask=Path(reference)/'satpy_geocolor_v060/composites/gshhs_land_water_mask_3km_i.tif'
    if digest(mask)!=identity['source_sha256']:raise ValueError('Land/water reference changed; inputs preserved')
