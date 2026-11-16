"""Fresh Blender process proves saved asset independence and editable controls."""
import hashlib
import json
from pathlib import Path
import sys
import bpy


def main():
    package=Path(bpy.data.filepath).parent.resolve()
    manifest=package/'commit.json';data=json.loads(manifest.read_text(encoding='utf-8'))
    allowed={(package/a['path']).resolve():a for a in data['assets']}
    images=[]
    for image in bpy.data.images:
        if image.source not in ('FILE','SEQUENCE','MOVIE'): continue
        if image.source!='FILE': raise ValueError('Old weather video/sequence still linked')
        path=Path(bpy.path.abspath(image.filepath)).resolve()
        if path not in allowed: raise ValueError('Dependency outside committed package: '+str(path))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=allowed[path]['sha256']: raise ValueError('Asset changed')
        if list(image.size)[::-1]!=allowed[path]['shape']: raise ValueError('Asset decode dimensions differ')
        # Force actual pixel decoding; does not depend on HSD readers or L1.
        image.pixels[0]
        images.append(str(path.relative_to(package)))
    if len(set(images))!=4: raise ValueError('Four independent layers required')
    controls=['groundEnabled','groundBrightness','groundHue','groundSaturation','groundTintR','groundTintG','groundTintB',
              'blueAtmosphere','nightAirglow','newAirglow','newGlowDensity','newGlowThickness','newGlowHue','newGlowSaturation','newGlowBrightness',
              *[prefix+suffix for prefix in ('blue','warm') for suffix in ('Density','Thickness','Hue','Saturation','Brightness')]]
    for scene in bpy.data.scenes:
        controller=bpy.data.objects[scene.camera['earthstudio_controller']]
        scene.frame_set(1)
        paths=json.loads(controller['earthstudio_parameter_paths'])
        for key in controls:
            owner,attribute=paths['["'+key+'"]'].rsplit('.',1)
            target=controller.path_resolve(owner);before=getattr(target,attribute)
            trial=not before if key in ('groundEnabled','blueAtmosphere','nightAirglow','newAirglow') else 0.0
            setattr(target,attribute,trial)
            if getattr(target,attribute)!=trial:raise ValueError('Control is not editable: '+key)
            setattr(target,attribute,before)
            if getattr(target,attribute)!=before:raise ValueError('Control restore failed: '+key)
        if not scene.get('production_single_scan'): raise ValueError('Unverified sequence')
    proof=dict(schema='earthstudio.blender.production_reopen.v1',
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),independent_of_l1=True,
        verified_capabilities=controls,images=images,blender_version=bpy.app.version_string,
        blend=dict(path=Path(bpy.data.filepath).name,bytes=Path(bpy.data.filepath).stat().st_size,
                   sha256=hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest()),
        limitation='Pixel decode and control editing verified; render/visual acceptance reported separately')
    (package/'blender_reopen.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PRODUCTION_REOPEN_VERIFIED',json.dumps(proof),flush=True)


if __name__=='__main__': main()
