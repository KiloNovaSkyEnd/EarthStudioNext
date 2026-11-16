"""Observed-input regression audit: changed display, unchanged classifications."""
from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw
from ges.cloud_evidence import LOW_CLASSES

ROOT=Path(__file__).resolve().parents[1]


def main():
    old=ROOT/'data/processed/validation_v5';new=ROOT/'data/processed/validation_v6'
    matrix=json.loads((new/'validation_matrix.json').read_text());report=[]
    for row in matrix:
        newpath=ROOT/row['texture'];oldpath=old/newpath.relative_to(new)
        nm=json.loads(newpath.with_suffix('.json').read_text());om=json.loads(oldpath.with_suffix('.json').read_text())
        nc=np.asarray(Image.open(newpath.parent/nm['cloud_evidence_classes']));oc=np.asarray(Image.open(oldpath.parent/om['cloud_evidence_classes']))
        assert np.array_equal(nc,oc),'Changed low cloud classifications'
        supported=np.isin(nc,LOW_CLASSES)
        a=np.asarray(Image.open(oldpath));b=np.asarray(Image.open(newpath))
        assert np.array_equal(a[~supported],b[~supported]),'Neutral texture changed'
        assert (b[...,3]>=a[...,3]).all(),'Existing cloud opacity reduced'
        before=(a[...,2]>a[...,0])&(a[...,3]>0);after=(b[...,2]>b[...,0])&(b[...,3]>0)
        assert not (before&~after).any(),'Existing blue removed'
        assert not (after&~supported).any(),'Unsupported blue introduced'
        for field in ['coverage','eligible']:
            assert np.array_equal(np.asarray(Image.open(newpath.with_name(newpath.stem+'_'+field+'.png'))),
                                  np.asarray(Image.open(oldpath.with_name(oldpath.stem+'_'+field+'.png'))))
        probe=json.loads((ROOT/row['blender_scene']).with_name('verification.json').read_text())
        weak=[r for r in probe['checks'] if r['name']=='WeakCloudTextureProbe']
        assert len(weak)==1 and weak[0]['max_rgb_error']<.04,'Weak-cloud globe color not verified'
        report.append({'case':row['case'],'class_map_exact':True,'coverage_night_exact':True,
                       'non_supported_rgba_exact':True,'blue_v5':int(before.sum()),'blue_v6':int(after.sum()),
                       'newly_visible_supported_blue':int((after&~before).sum()),'lost_existing_blue':0,
                       'weak_cloud_globe_rgb_error':weak[0]['max_rgb_error'],
                       'classification_accuracy_metric':False})
        if row['case']=='himawari8_1640':
            h,w=nc.shape;lat=90-(np.arange(h)+.5)*360/w;lon=-180+(np.arange(w)+.5)*360/w
            yy=np.flatnonzero((lat>=18)&(lat<=42));xx=np.flatnonzero((lon>=95)&(lon<=125))
            sl=(slice(yy[0],yy[-1]+1),slice(xx[0],xx[-1]+1))
            report[-1]['china_bbox_blue_v5']=int(before[sl].sum());report[-1]['china_bbox_blue_v6']=int(after[sl].sum())
            report[-1]['region']='95..125E,18..42N incl seas; equal-angle display pixels, not cloud amount/area'
    (new/'visibility_regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    # Exact same 4K globe camera; contact sheet is a downscaled inspection aid.
    sheet=Image.new('RGB',(3840,1120),(12,15,22));draw=ImageDraw.Draw(sheet)
    for i,folder in enumerate([old,new]):
        with Image.open(folder/'blender/himawari8_1640/night_pacific_closeup.png') as im:
            view=im.convert('RGB').resize((1920,1080),Image.Resampling.LANCZOS)
        sheet.paste(view,(i*1920,40));draw.text((i*1920+16,12),
            ('V5 spectral veto' if i==0 else 'V6 supported low visibility')+' / H8 2020-10-29 16:40 UTC / same camera',fill=(235,240,255))
    sheet.save(new/'low_visibility_before_after.png')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
