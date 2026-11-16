"""Versioned template/decoder contract; never includes weather UTC in its key."""
import hashlib,json
from pathlib import Path
from .assets import digest

ROOT=Path(__file__).resolve().parents[2]
FILES=['resources/blender/production_template.blend','scripts/blender_build_production_layers.py',
       'scripts/blender_verify_production_layers.py','scripts/blender_support/production_layers.py',
       'scripts/blender_support/layered_atmosphere.py','ges_next/production/verification.py',
       'ges_next/production/batch_assets.py','ges_next/production/template_certificate.py',
       'ges_next/production/certificate_identity.py']
FILES+=['ges_next/production/profile.py','ges_next/production/jpeg_layers.py',
        'ges_next/production/h9_job.py','ges_next/production/h9_layers.py',
        'ges_next/production/validation_session.py','ges_next/pipeline/worker_validation.py',
        'ges/earth_validation/solar_shared.py','ges/earth_validation/solar_satpy_config/composites/ahi.yaml',
        'ges/earth_validation/bootstrap.py','ges_next/production/__main__.py']
FILES+=['resources/blender/dual_airglow_r3.blend','scripts/blender_support/dual_airglow.py','scripts/blender_support/airglow_transport_nodes.py','scripts/blender_support/airglow_parameters.py']
FILES+=['ges_next/production/qualified_static.py', 'resources/references/qualified_h9_landmask_v1/manifest.json', 'resources/references/qualified_h9_landmask_v1/eee9736ff7b78420e1cc09ca9c27e08508293b524767bdf7be86fe1353d19361.json']


def asset_identity(data):
    value=dict(grid={k:data['grid'][k] for k in ('shape','extent','crs')},
        encoding=data['colour_encoding'],
        layers=sorted([dict(role=a['role'],shape=a['shape'],encoding=a['encoding'],quality=a.get('quality'),
            subsampling=a.get('subsampling'),lossless=a.get('lossless'),colour_space=a.get('colour_space'),
            static_sha256=a['sha256'] if a['role']=='shared-static-night-background' else None) for a in data['assets']],key=lambda a:a['role']))
    if data.get('night_recipe'):value['night_recipe']=data['night_recipe']['recipe']
    return value


def identity(data,blender):
    files=list(FILES)
    if data.get('night_recipe'):
        files+=['ges_next/production/neutral_night.py','ges_next/algorithms/night_modes.py','ges_next/production/night_layers.py','ges_next/production/rebuild_recipe.py','ges_next/production/h9_source.py','ges_next/production/qualified_static.py','resources/references/qualified_h9_landmask_v1/eee9736ff7b78420e1cc09ca9c27e08508293b524767bdf7be86fe1353d19361.json','resources/references/qualified_h9_landmask_v1/manifest.json']
        files += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'ges_next/algorithms/aivis').glob('*.py'))]
    return dict(schema='earthstudio.template_contract.v1',blender_executable=str(Path(blender).resolve()),
        blender_sha256=digest(blender),engine={name:digest(ROOT/name) for name in dict.fromkeys(files)},**asset_identity(data))


def key(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
