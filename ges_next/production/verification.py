"""Required independent-Blender proof and complete retained-asset integrity."""
import json
from pathlib import Path
from PIL import Image
Image.MAX_IMAGE_PIXELS=500_000_000
from .assets import digest, verify_assets


def validate_reopen(job, step, evidence,decode_images=True,enforce_current_contract=True):
    manifest=Path(step['manifest'])
    if digest(manifest) != step['hash']: raise ValueError('Committed manifest changed')
    data=json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('schema') != 'earthstudio.layered_jpeg.v1': raise ValueError('Unsupported production commit')
    verify_assets(manifest.parent,data['assets'])
    if json.loads(job['profile']).get('require_rebuild_recipe') and not data.get('rebuild_recipe'):
        raise ValueError('Rebuild recipe missing; inputs must be retained')
    if data.get('rebuild_recipe'):
        verify_assets(manifest.parent,[data['rebuild_recipe']])
        from .rebuild_recipe import validate
        recipe=json.loads((manifest.parent/data['rebuild_recipe']['path']).read_text(encoding='utf-8'))
        validate(recipe)
        if recipe['utc']!=data['utc']: raise ValueError('Rebuild recipe identifies another scan')
    required={'stock-clouds-day-without-ground-background','shared-static-night-background','stock-ground-transmission','actual-observation-support'}
    if not required.issubset({a['role'] for a in data['assets']}): raise ValueError('Editable layers incomplete')
    profile=json.loads(job['profile'])
    if profile.get('night_recipe') and data.get('night_recipe',{}).get('recipe')!=profile['night_recipe']:
        raise ValueError('Optional night output recipe differs from job profile')
    if profile.get('night_recipe') and data['night_recipe'].get('max_day_branch_difference_dn')!=0:
        raise ValueError('Optional night mode changed full-day branch')
    evidence=Path(evidence)
    if not evidence.resolve().is_relative_to(manifest.parent): raise ValueError('Reopen proof outside package')
    proof=json.loads(evidence.read_text(encoding='utf-8'))
    certified=proof.get('schema')=='earthstudio.blender.template_assets.v1'
    if profile.get('grid_shape'):
        if data.get('grid',{}).get('shape')!=profile['grid_shape']:raise ValueError('Committed grid differs from selected profile')
        if any(item['shape']!=(profile.get('night_grid_shape',profile['grid_shape']) if item['role']=='shared-static-night-background' else profile['grid_shape']) for item in data['assets']):raise ValueError('Layer grid differs from selected profile')
        for item in data['assets']:
            if item['role'] in ('stock-clouds-day-without-ground-background','shared-static-night-background'):
                if item.get('encoding')!='JPEG' or item.get('quality')!=profile['quality'] or item.get('subsampling')!='4:4:4':
                    raise ValueError('JPEG encoding differs from selected profile')
    for item in data['assets']:
        with Image.open(manifest.parent/item['path']) as image:
            if list(image.size)[::-1] != item['shape']: raise ValueError('Retained image shape differs')
            if decode_images and not certified:
                from .validation_session import load_image_once
                load_image_once(manifest.parent/item['path'],image)
    if certified:
        if proof.get('manifest_sha256')!=step['hash'] or proof.get('utc')!=data['utc'] or proof.get('independent_of_l1') is not True:
            raise ValueError('Per-frame asset evidence does not identify this scan')
        from .template_certificate import validate
        if decode_images:
            from .batch_assets import check_pixels
            check_pixels(manifest.parent,data)
        validate(manifest.parent,data,profile,proof,require_current=enforce_current_contract)
        return True
    if proof.get('schema') != 'earthstudio.blender.production_reopen.v1' or proof.get('manifest_sha256') != step['hash']:
        raise ValueError('Reopen proof does not identify this committed package')
    if proof.get('independent_of_l1') is not True: raise ValueError('L1 independence not verified')
    blend=proof.get('blend')
    if not blend or not blend['path'].endswith('.blend'): raise ValueError('Saved editable Blender scene required')
    verify_assets(manifest.parent,[blend])
    requested=set(json.loads(job['profile']).get('required_capabilities',[]))
    if not requested.issubset(proof.get('verified_capabilities',[])): raise ValueError('Required editing controls not verified')
    return True
