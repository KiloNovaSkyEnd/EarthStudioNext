"""Bounded actual Goni observations; regional HSD bands + archived HDF5 ranges."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import re
from ges.catalog import s3_client,list_objects,utc_time,Scene
from ges.download import download_scene,cached_bytes
from ges.storage import load_config,preflight


def inventory(s3,t):
    prefix=f'AHI-L1b-FLDK/{t:%Y/%m/%d/%H%M}/';objects=list_objects(s3,'noaa-himawari8',prefix)
    # Regional vertical strips, not a claimed complete full disk. B03 is only
    # requested while the regional scene can contain genuine daylight.
    bands=['B13']+(['B03'] if t.hour<10 else [])
    selected=[]
    for band in bands:
        for segment in range(2,7):
            matches=[o for o in objects if f'_{band}_FLDK_' in o['Key'] and f'_S{segment:02d}10.' in o['Key']]
            if len(matches)!=1:raise ValueError(f'Exact HSD regional segment absent: {t} {band} {segment}')
            selected+=matches
    scene=Scene('himawari8_goni_region','noaa-himawari8',prefix,t,tuple(o['Key'] for o in selected),
                sum(o['Size'] for o in selected),'AHI-HSD-regional-segments',tuple(o['Size'] for o in selected))
    l2prefix=f'AHI-L2-FLDK-Clouds/{t:%Y/%m/%d/%H%M}/';l2=list_objects(s3,'noaa-himawari8',l2prefix)
    support=[]
    for kind in ['MASK','HEIGHT']:
        match=[o for o in l2 if f'CLOUD_{kind}_EN.nc' in o['Key']]
        if len(match)!=1:raise ValueError(f'Exact L2 support absent: {t} {kind}')
        o=match[0];support.append({'kind':kind,'key':o['Key'],'size':o['Size'],'etag':o['ETag']})
    return scene,support


def main():
    cfg=load_config();s3=s3_client();folder=cfg.processed_dir/'goni_film_v1';folder.mkdir(parents=True,exist_ok=True)
    times=[utc_time('2020-10-30T04:00:00Z')+timedelta(minutes=20*i) for i in range(31)]
    with ThreadPoolExecutor(max_workers=6) as pool:plans=list(pool.map(lambda t:inventory(s3,t),times))
    all_hsd=sum(s.total_bytes for s,_ in plans)
    cached_hsd=sum(cached_bytes(s,cfg.raw_dir/s.scene_id) for s,_ in plans)
    total=all_hsd-cached_hsd
    # Shared total cap is reserved up front. Actual L2 blocks are checked again
    # per fetch; max120MB per scene, never whole623MB height products.
    range_reserve=31*60_000_000
    prior_unused=sum(p.stat().st_size for p in (cfg.raw_dir/'goni_l2_ranges').glob('*/MASK/*.bin'))
    check=preflight(all_hsd+range_reserve+prior_unused,cfg.raw_dir,cfg,existing_bytes=cached_hsd)
    document={'satellite':'himawari8','nominal_start_utc':times[0].isoformat(),'nominal_end_utc':times[-1].isoformat(),
              'actual_acquisitions':31,'cadence_minutes':20,'hsd_new_bytes':total,'hsd_total_bytes':all_hsd,'l2_range_reserve_bytes':range_reserve,
              'retained_pilot_range_bytes':prior_unused,
              'preflight':check,'regional_segments':list(range(2,7)),'l2_native_slice_yx':[600,3300,700,4400],
              'scenes':[{'nominal_utc':s.observed_utc.isoformat(),'manifest':str((cfg.raw_dir/s.scene_id/'scene.json').resolve()),
                         'support':support} for s,support in plans]}
    (folder/'inventory.json').write_text(json.dumps(document,indent=2),encoding='utf-8')
    print('PREFLIGHT',json.dumps({k:document[k] for k in ['hsd_new_bytes','l2_range_reserve_bytes','preflight']}),flush=True)
    def fetch(item):
        scene,_=item;p=download_scene(s3,scene,cfg.raw_dir,cfg)
        print('RAW',scene.observed_utc.isoformat(),scene.total_bytes,flush=True);return p
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(fetch,plans))
    print('INVENTORY',folder/'inventory.json',flush=True)


if __name__=='__main__':main()
