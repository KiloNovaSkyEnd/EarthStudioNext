"""Reproducible same-recipe, cross-time/cross-sensor AND Blender validation."""
import argparse,json,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run(args):
    subprocess.run([str(x) for x in args],cwd=ROOT,check=True)


def validate(blender,width=8192,meteosat_only=False,output=None):
    folder=Path(output).resolve() if output else ROOT/'data/processed/validation_v9'
    folder.mkdir(exist_ok=True,parents=True)
    cases=[('himawari8_1640','himawari8_20201029T164000Z','himawari8_cloud_l2_20201029T164000Z'),
           ('himawari8_1740','himawari8_20201029T174000Z','himawari8_cloud_l2_20201029T174000Z'),
           ('goes16_0640','goes16_20201029T064019Z','goes16_cloud_l2_20201029T064000Z'),
           ('goes16_0740','goes16_20201029T074019Z','goes16_cloud_l2_20201029T074000Z')]
    report=json.loads((folder/'validation_matrix.json').read_text())[:4] if meteosat_only else []
    for name,ir,l2 in ([] if meteosat_only else cases):
        print('VALIDATE',name,flush=True);out=folder/name
        stem='ahi_evidence_night' if name.startswith('himawari') else 'goes16_evidence_night'
        texture=out/(stem+'.png')
        run([sys.executable,'-m','ges','cloud-evidence','--ir-manifest',f'data/raw/{ir}/scene.json',
             '--l2-manifest',f'data/raw/{l2}/scene.json','--lights','data/raw/reference/BlackMarble_2016_3km.jpg',
             '--out',out,'--width',width])
        scene=folder/'blender'/name/'earth.blend';scene.parent.mkdir(parents=True,exist_ok=True)
        run([blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
             '--cloud',texture,'--night-reference',out/(stem+'_surface.png'),'--out',scene,
             '--preview',scene.parent/'earth_4k.png','--preview-width','3840'])
        run([blender,'--background',scene,'--python-exit-code','1','--python','tests/blender_verify.py','--',
             '--himawari-only' if name.startswith('himawari') else '--goes-only'])
        meta=json.loads(texture.with_suffix('.json').read_text())
        probe=json.loads((scene.parent/'verification.json').read_text())
        report.append({'case':name,'texture':str(texture.relative_to(ROOT)),
                       'blender_scene':str(scene.relative_to(ROOT)),
                       'display_recipe':meta['display_recipe'],'blue_pixels':meta['displayed_blue_pixels'],
                       'scan_start_utc':meta['scan_start_utc'],'scan_end_utc':meta['scan_end_utc'],
                       'blender_passed':probe['passed'],'classification_accuracy_verified':False})
        (folder/'validation_matrix.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for platform in ['meteosat_msg4','meteosat_msg1']:
        print('VALIDATE height-supported',platform,flush=True);out=folder/(platform+'_supported_v2')
        texture=out/(platform+'_evidence_night.png')
        if not texture.with_suffix('.json').exists():
            run([sys.executable,'-m','ges','cloud-evidence','--ir-manifest',f'data/raw/{platform}_20201029T163010Z/scene.json',
                 '--l2-manifest',f'data/raw/{platform}_cloud_l2_20201029T163000Z/scene.json',
                 '--lights','data/raw/reference/BlackMarble_2016_3km.jpg','--out',out,'--width',width])
        scene=folder/'blender'/(platform+'_supported_v2')/'earth.blend'
        run([blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
             '--cloud',texture,'--night-reference',out/(platform+'_evidence_night_surface.png'),'--out',scene,
             '--preview',scene.parent/'earth_4k.png','--preview-width','3840'])
        run([blender,'--background',scene,'--python-exit-code','1','--python','tests/blender_verify.py','--',
             '--coverage-from-texture','--view-longitude','55','--view-latitude','10'])
        report.append({'case':platform,'texture':str(texture.relative_to(ROOT)),
                       'blender_scene':str(scene.relative_to(ROOT)),
                       'blue_cloud_support':'good cloud mask + good CTH below 3 km; no phase retrieval; not identical pressure classification',
                       'blender_passed':True,'independent_footprint_check':False,
                       'classification_accuracy_verified':False})
        (folder/'validation_matrix.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--width',type=int,default=8192)
    p.add_argument('--meteosat-only',action='store_true')
    p.add_argument('--output')
    a=p.parse_args();validate(a.blender,a.width,a.meteosat_only,a.output)
