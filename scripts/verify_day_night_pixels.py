"""Audit actual combined pixels against accepted night and measured day files."""
from pathlib import Path
import json
import numpy as np
from PIL import Image
from ges.solar import solar_weights
from ges.catalog import utc_time

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'data/processed/day_night_v1';p=folder/'earth_day_night.png'
    m=json.loads(p.with_suffix('.json').read_text());stamp=utc_time(m['reference_utc'])
    result=np.asarray(Image.open(p));day=np.asarray(Image.open(folder/'daylight/goes_daylight.png'))
    oldpath=ROOT/'data/processed/validation_v9/global/global_night.png'
    old=np.asarray(Image.open(oldpath));om=json.loads(oldpath.with_suffix('.json').read_text())
    surface=np.asarray(Image.open(oldpath.parent/om['night_surface']))
    coverage=np.asarray(Image.open(oldpath.parent/om['source_ir_coverage']))>0
    oldflat=np.rint(old[...,:3]*(old[...,3:4].astype(np.float32)/255)+surface*(1-old[...,3:4].astype(np.float32)/255)).astype(np.uint8)
    records=json.loads((ROOT/'data/processed/validation_v9/fusion_sources.json').read_text())
    sources=[]
    for r in records:
        q=Path(r['image']);meta=json.loads(q.with_suffix('.json').read_text())
        sources.append((meta,np.asarray(Image.open(q.parent/meta['source_ir_coverage']))>0))
    h,w=coverage.shape;lon=-180+(np.arange(w)+.5)*360/w
    counts={'deep_night_exact_pixels':0,'fully_selected_day_exact_pixels':0,'missing_day_not_filled_pixels':0,
            'twilight_partial_availability_pixels':0}
    daymap=np.asarray(Image.open(p.with_name(p.stem+'_day_contribution.png')))
    nightmap=np.asarray(Image.open(p.with_name(p.stem+'_night_contribution.png')))
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        solar=solar_weights(stamp,lon[None,:],lat[:,None]);weight=solar.day_cloud
        deep=coverage[sl].copy()
        for meta,cov in sources:
            first=solar_weights(utc_time(meta['scan_start_utc']),lon[None,:],lat[:,None]).elevation_deg
            last=solar_weights(utc_time(meta['scan_end_utc']),lon[None,:],lat[:,None]).elevation_deg
            deep&=~cov[sl]|(np.maximum(first,last)<=-12)
        assert np.array_equal(result[sl][deep,:3],oldflat[sl][deep]),'Accepted deep-night RGB changed'
        assert (result[sl][deep,3]==255).all()
        full=(weight>=1)&(day[sl,...,3]==255)
        assert np.array_equal(result[sl][full],day[sl][full]),'Fully selected daytime RGB changed'
        missing=(weight>=1)&(day[sl,...,3]==0)&coverage[sl]
        assert not result[sl][missing].any(),'Missing day VIS filled with IR/reference'
        assert not daymap[sl][solar.elevation_deg<=0].any(),'VIS appeared on night side'
        assert (abs(result[sl,...,3].astype(int)-daymap[sl].astype(int)-nightmap[sl].astype(int))<=1).all()
        counts['deep_night_exact_pixels']+=int(deep.sum());counts['fully_selected_day_exact_pixels']+=int(full.sum())
        counts['missing_day_not_filled_pixels']+=int(missing.sum())
        counts['twilight_partial_availability_pixels']+=int(((weight>0)&(weight<1)&(result[sl,...,3]>0)&(result[sl,...,3]<255)).sum())
    assert all(v>0 for v in counts.values()),'Real-scene test did not exercise a required branch'
    report={**counts,'reference_utc':m['reference_utc'],'no_day_contribution_at_or_below_horizon':True,
        'source_weight_alpha_consistency':True,'is_independent_cloud_truth':False,
        'daylight_scope':'GOES16 only; missing VIS remains unavailable'}
    (folder/'pixel_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
