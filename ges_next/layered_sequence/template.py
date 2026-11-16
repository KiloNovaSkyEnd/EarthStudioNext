"""A certified frame can seed a sequence without owning a per-frame blend."""
import json
from pathlib import Path
from ges_next.production.assets import digest


def select(package):
    package=Path(package);blend=package/'EarthStudio_JPEG_独立灯光.blend'
    if blend.is_file():return blend
    evidence=package/'asset_verification.json'
    if not evidence.is_file():raise ValueError('请先完成完整Blender验证或逐帧模板资产验证')
    proof=json.loads(evidence.read_text(encoding='utf-8'))
    certificate=json.loads((package/proof['certificate']['path']).read_text(encoding='utf-8'))
    from ges_next.production.verification import validate_reopen
    validate_reopen(dict(root=str(package),profile=json.dumps(certificate['profile'])),
        dict(manifest=str(package/'commit.json'),hash=digest(package/'commit.json')),evidence,enforce_current_contract=False)
    return Path(certificate['anchor'])/'EarthStudio_JPEG_独立灯光.blend'
