"""Compare real v6/v8 products, keeping source labels and coverage fixed."""
from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw
from ges.cloud_evidence import LOW_CLASSES

ROOT=Path(__file__).resolve().parents[1]


def main():
    old=ROOT/'data/processed/validation_v6';new=ROOT/'data/processed/validation_v8'
    matrix=json.loads((new/'validation_matrix.json').read_text());report=[]
    for row in matrix:
        path=ROOT/row['texture'];before=old/path.relative_to(new)
        a=np.asarray(Image.open(before));b=np.asarray(Image.open(path))
        c=np.asarray(Image.open(path.with_name(path.stem+'_classes.png')))
        supported=np.isin(c,LOW_CLASSES)
        for suffix in ['classes','coverage','eligible']:
            assert np.array_equal(np.asarray(Image.open(path.with_name(path.stem+'_'+suffix+'.png'))),
                                  np.asarray(Image.open(before.with_name(before.stem+'_'+suffix+'.png')))),suffix
        assert np.array_equal(a[~supported],b[~supported])
        ba=(a[...,2]>a[...,0])&(a[...,3]>0);bb=(b[...,2]>b[...,0])&(b[...,3]>0)
        assert not (bb&~supported).any()
        assert not (ba&~bb).any(),'Supported cloud vanished'
        probe=json.loads((ROOT/row['blender_scene']).with_name('verification.json').read_text())
        assert probe['passed'] and len(probe['checks'])==5
        report.append({'case':row['case'],'class_coverage_night_exact':True,
            'non_supported_rgba_exact':True,'supported_blue_lost':int((ba&~bb).sum()),
            'opaque_blue_v6':int((ba&(a[...,3]==255)).sum()),
            'opaque_blue_v8':int((bb&(b[...,3]==255)).sum()),
            'blue_display_pixels_v6':int(ba.sum()),'blue_display_pixels_v8':int(bb.sum()),
            'five_globe_probes_passed':True,'is_visual_acceptance_or_accuracy_metric':False})
    (new/'texture_regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(3840,1120),(12,15,22));draw=ImageDraw.Draw(sheet)
    for i,folder in enumerate([old,new]):
        view=Image.open(folder/'blender/himawari8_1640/night_pacific_closeup.png').convert('RGB')
        sheet.paste(view.resize((1920,1080),Image.Resampling.LANCZOS),(i*1920,40))
        draw.text((i*1920+16,12),('V6' if i==0 else 'V8 signed measured texture')+
                  ' / Himawari-8 2020-10-29 16:40 UTC / same camera',fill=(235,240,255))
    sheet.save(new/'low_texture_before_after.png')
    # Matching geographic crop enlarges the low clouds, not the entire globe.
    w,h=Image.open(old/'himawari8_1640/ahi_evidence_night_preview.png').size
    bounds=tuple(int(v) for v in ((100+180)/360*w,(90-42)/180*h,
                                  (135+180)/360*w,(90-18)/180*h))
    crop_sheet=Image.new('RGB',(1600,590),(12,15,22));d=ImageDraw.Draw(crop_sheet)
    for i,folder in enumerate([old,new]):
        im=Image.open(folder/'himawari8_1640/ahi_evidence_night_preview.png').convert('RGB').crop(bounds)
        crop_sheet.paste(im.resize((800,549),Image.Resampling.LANCZOS),(i*800,40))
        d.text((i*800+12,12),('V6' if i==0 else 'V8')+' / 100..135E, 18..42N / 2020-10-29 16:40 UTC',fill='white')
    crop_sheet.save(new/'china_low_texture_before_after.png')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
