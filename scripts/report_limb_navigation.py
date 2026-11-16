"""v8/v9 navigation audit; accepted v8 display recipe stays unchanged."""
from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]


def main():
    old=ROOT/'data/processed/validation_v8';new=ROOT/'data/processed/validation_v9'
    matrix=json.loads((new/'validation_matrix.json').read_text());report=[]
    for row in matrix:
        p=ROOT/row['texture'];q=old/p.relative_to(new)
        m=json.loads(p.with_suffix('.json').read_text());before=json.loads(q.with_suffix('.json').read_text())
        for key in ['display_recipe','supported_low_visibility','low_rgb_shading']:
            assert m[key]==before[key],f'Accepted palette/transfer changed: {key}'
        assert m['navigation_recipe']=='inverse-native-geos-pixel-footprint-v1'
        a=np.asarray(Image.open(q.with_name(q.stem+'_coverage.png')))>0
        b=np.asarray(Image.open(p.with_name(p.stem+'_coverage.png')))>0
        pixels=np.asarray(Image.open(p));night=np.asarray(Image.open(p.with_name(p.stem+'_eligible.png')))>0
        assert not pixels[...,3][~b|~night].any()
        probe=json.loads((ROOT/row['blender_scene']).with_name('verification.json').read_text())
        assert probe['passed']
        report.append({'case':row['case'],'accepted_v8_color_recipe_unchanged':True,
            'coverage_v8':int(a.sum()),'coverage_v9':int(b.sum()),
            'native_navigation_only':int((b&~a).sum()),'kd_only_removed':int((a&~b).sum()),
            'opacity_outside_native_coverage_or_night':0,'five_globe_probes_passed':True,
            'is_new_observation_or_accuracy_gain':False})
    (new/'navigation_regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    gm=json.loads((new/'global/global_night.json').read_text())
    assert not gm.get('grazing_display_guard',{}).get('enabled',False),'Rejected stronger guard must not be promoted as final'
    sheet=Image.new('RGB',(3840,1120),(12,15,22));draw=ImageDraw.Draw(sheet)
    for i,folder in enumerate([old,new]):
        p=folder/'blender/global/earth_4k.png'
        if not p.exists():raise FileNotFoundError('Finish global globe validation before generating the before/after sheet')
        im=Image.open(p).convert('RGB').resize((1920,1080),Image.Resampling.LANCZOS)
        sheet.paste(im,(i*1920,40))
        draw.text((i*1920+16,12),('V8 accepted color / KD-tree' if i==0 else 'V9 same color / inverse native navigation + grazing limb fade')+
                  ' / 2020-10-29 16:40 UTC',fill='white')
    sheet.save(new/'limb_globe_before_after.png')
    detail=Image.new('RGB',(2900,680),(12,15,22));d=ImageDraw.Draw(detail)
    for i,folder in enumerate([old,new]):
        im=Image.open(folder/'blender/global/earth_4k.png').convert('RGB').crop((1250,160,2700,800))
        detail.paste(im,(i*1450,40));d.text((i*1450+12,12),
            ('V8 accepted color' if i==0 else 'V9 same color / native navigation')+' / same camera / remaining MSG1 wedge retained',fill='white')
    detail.save(new/'limb_north_detail_before_after.png')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
