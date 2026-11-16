"""Audit v3 actual observations and create same-camera v1/v3 comparisons."""
from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw
from ges.catalog import utc_time
from ges.solar import solar_weights

ROOT=Path(__file__).resolve().parents[1]


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',default='data/processed/day_night_v3');args=parser.parse_args()
    folder=ROOT/args.out;oldfolder=ROOT/'data/processed/day_night_v1'
    p=folder/'earth_day_night.png';meta=json.loads(p.with_suffix('.json').read_text());stamp=utc_time(meta['reference_utc'])
    out=np.asarray(Image.open(p));old=np.asarray(Image.open(oldfolder/'earth_day_night.png'))
    day=np.asarray(Image.open(folder/'daylight/goes_daylight.png'))
    prevday=np.asarray(Image.open(oldfolder/'daylight/goes_daylight.png'))
    np.testing.assert_array_equal(day[...,3],prevday[...,3],err_msg='VIS quality mask changed')
    dw=np.asarray(Image.open(p.with_name(p.stem+'_day_contribution.png')))
    nw=np.asarray(Image.open(p.with_name(p.stem+'_night_contribution.png')))
    gap=np.asarray(Image.open(p.with_name(p.stem+'_measured_ir_day_gap.png')))>0
    nightpath=folder/'transition_global/transition_ir.png'
    nm=json.loads(nightpath.with_suffix('.json').read_text())
    coverage=np.asarray(Image.open(nightpath.parent/nm['source_ir_coverage']))>0
    records=json.loads((ROOT/'data/processed/validation_v9/fusion_sources.json').read_text());sources=[]
    for r in records:
        q=Path(r['image']);m=json.loads(q.with_suffix('.json').read_text())
        sources.append((m,np.asarray(Image.open(q.parent/m['source_ir_coverage']))>0))
    h,w=coverage.shape;lon=-180+(np.arange(w)+.5)*360/w
    counts={'deep_night_exact_pixels':0,'pure_day_exact_pixels':0,'day_gap_measured_ir_pixels':0,'former_black_gap_now_ir_pixels':0,'both_missing_transparent_pixels':0,'mixed_day_ir_pixels':0}
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        elev=solar_weights(stamp,lon[None,:],lat[:,None]).elevation_deg
        assert not dw[sl][elev<=0].any(),'Night visible contribution'
        assert (abs(out[sl,...,3].astype(int)-dw[sl].astype(int)-nw[sl].astype(int))<=1).all()
        assert (out[sl][coverage[sl],3]==255).all(),'Available IR became black transparent gap'
        pure=dw[sl]==255
        # Stored contribution rounds at 1/255; allow one DN at its rounded endpoint.
        assert np.max(abs(out[sl][pure].astype(int)-day[sl][pure].astype(int)),initial=0)<=1
        both=(day[sl,...,3]==0)&~coverage[sl]
        assert not out[sl][both].any(),'Both-missing observation invented'
        assert not dw[sl][gap[sl]].any(),'IR gap labeled as visible'
        assert (nw[sl][gap[sl]]==255).all()
        deep=coverage[sl].copy()
        for m,c in sources:
            first=solar_weights(utc_time(m['scan_start_utc']),lon[None,:],lat[:,None]).elevation_deg
            last=solar_weights(utc_time(m['scan_end_utc']),lon[None,:],lat[:,None]).elevation_deg
            deep&=~c[sl]|(np.maximum(first,last)<=-12)
        np.testing.assert_array_equal(out[sl][deep],old[sl][deep],err_msg='Accepted deep night changed')
        counts['deep_night_exact_pixels']+=int(deep.sum());counts['pure_day_exact_pixels']+=int(pure.sum())
        counts['day_gap_measured_ir_pixels']+=int(gap[sl].sum())
        counts['former_black_gap_now_ir_pixels']+=int(((old[sl,...,3]==0)&(out[sl,...,3]==255)&coverage[sl]).sum())
        counts['both_missing_transparent_pixels']+=int(both.sum())
        counts['mixed_day_ir_pixels']+=int(((dw[sl]>0)&(dw[sl]<255)&(nw[sl]>0)).sum())
    assert all(v>0 for v in counts.values())
    source_checks=[]
    for index,(m,cov) in enumerate(sources,1):
        before=next((oldfolder/'transition_sources'/str(index)).glob('*_transition_ir.png'))
        after=next((folder/'transition_sources'/str(index)).glob('*_transition_ir.png'))
        oldrgba=np.asarray(Image.open(before));newrgba=np.asarray(Image.open(after))
        sm=json.loads(after.with_suffix('.json').read_text())
        classes=np.asarray(Image.open(sm['cloud_evidence_classes']))
        deep_count=neutral_count=changed_count=0
        for row in range(0,h,128):
            sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
            first=solar_weights(utc_time(m['scan_start_utc']),lon[None,:],lat[:,None]).elevation_deg
            last=solar_weights(utc_time(m['scan_end_utc']),lon[None,:],lat[:,None]).elevation_deg
            deep=np.maximum(first,last)<=-12
            np.testing.assert_array_equal(newrgba[sl][deep],oldrgba[sl][deep])
            neutral=(np.maximum(first,last)>=-6)&cov[sl]
            np.testing.assert_array_equal(newrgba[sl][neutral,0],newrgba[sl][neutral,2])
            # Canonical transparent black versus transparent white is not a
            # displayed cloud change. Still compare alpha everywhere and RGB
            # whenever either image has nonzero alpha.
            visible=(newrgba[sl,...,3]>0)|(oldrgba[sl,...,3]>0)
            changed=np.any(newrgba[sl]!=oldrgba[sl],axis=-1)&visible
            unsupported=~np.isin(classes[sl],[2,6,7,8,9])
            np.testing.assert_array_equal(newrgba[sl,...,3][unsupported],oldrgba[sl,...,3][unsupported])
            assert np.isin(classes[sl][changed],[2,6,7,8,9]).all(),'Warm twilight support expanded beyond original L2 classes'
            deep_count+=int(deep.sum());neutral_count+=int(neutral.sum());changed_count+=int(changed.sum())
        source_checks.append({'satellite':sm['satellite'],'deep_night_rgba_exact_grid_pixels':deep_count,
                              'neutral_ir_no_blue_observed_pixels':neutral_count,'changed_only_inside_original_low_top_support':changed_count})
    report={**counts,'transition_source_checks':source_checks,'visible_mask_bit_identical_to_v1':True,'all_actual_ir_coverage_opaque':True,
            'no_vis_at_night':True,'is_independent_cloud_truth':False,'grid':'8192x4096 equal-angle counts, not area/cloud accuracy',
            'solar_weight_model':'Miller2020 eq5/13; rayleigh correction is an approximation, not full CIRA SHAC'}
    (folder/'pixel_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(2000,3*600+50),(10,14,22));draw=ImageDraw.Draw(sheet)
    draw.text((15,15),'BEFORE v1 (left) / AFTER v3 (right) - same UTC, camera, geometry',fill='white')
    for row,name in enumerate(['day_americas_4k.png','terminator_4k.png','night_asia_4k.png']):
        for col,base in enumerate([oldfolder,folder]):
            im=Image.open(base/'blender'/name).convert('RGB');im.thumbnail((1000,562),Image.Resampling.LANCZOS)
            sheet.paste(im,(col*1000,50+row*600));draw.text((col*1000+12,50+row*600+565),name,fill='white')
    sheet.save(folder/'day_night_before_after.png')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
