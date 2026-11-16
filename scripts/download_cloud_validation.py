"""Bounded, authentic cross-time validation inputs; uses normal atomic cache."""
from pathlib import Path
import re
from ges.catalog import Scene,s3_client,list_objects,utc_time,himawari_scene,goes_scene
from ges.download import download_scene,cached_bytes
from ges.storage import load_config,preflight


def plans(s3):
    t=utc_time('2020-10-29T17:40:00Z')
    yield himawari_scene(s3,t,('B13','B07'),0)
    prefix=f'AHI-L2-FLDK-Clouds/{t:%Y/%m/%d/%H%M}/'
    objects=list_objects(s3,'noaa-himawari8',prefix)
    selected=[next(o for o in objects if f'CLOUD_{kind}_EN.nc' in o['Key']) for kind in ['MASK','PHASE','HEIGHT']]
    yield Scene('himawari8_cloud_l2','noaa-himawari8',prefix,t,tuple(o['Key'] for o in selected),
                sum(o['Size'] for o in selected),'AHI-L2-FLDK-Clouds',tuple(o['Size'] for o in selected))
    for hour in [6,7]:
        t=utc_time(f'2020-10-29T{hour:02d}:40:00Z');ir=goes_scene(s3,t,'goes16',1)
        yield ir
        start=re.search(r'_s(\d+)_',ir.keys[0]).group(1)
        selected=[]
        for product in ['ACMF','ACTPF','ACHAF','CTPF']:
            objects=list_objects(s3,'noaa-goes16',f'ABI-L2-{product}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/')
            matches=[o for o in objects if f'_s{start}_' in o['Key']]
            if len(matches)!=1:raise ValueError('Missing or ambiguous exact matching ABI L2 scan')
            selected.extend(matches)
        yield Scene('goes16_cloud_l2','noaa-goes16','',t,tuple(o['Key'] for o in selected),
                    sum(o['Size'] for o in selected),'ABI-L2-ACM-ACTP-ACHA-CTP',tuple(o['Size'] for o in selected))


if __name__=='__main__':
    s3=s3_client();cfg=load_config();scenes=list(plans(s3))
    remaining=sum(s.total_bytes-cached_bytes(s,cfg.raw_dir/s.scene_id) for s in scenes)
    print('Aggregate download preflight:',preflight(remaining,cfg.raw_dir,cfg),flush=True)
    for scene in scenes:
        print('Downloading',scene.scene_id,scene.total_bytes,'bytes',flush=True)
        print('MANIFEST',download_scene(s3,scene,cfg.raw_dir,cfg),flush=True)
