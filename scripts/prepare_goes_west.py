"""Exact-scan GOES17 West scene/L2 support, 2020-10-29, normal atomic budget."""
import re
from ges.catalog import s3_client,goes_scene,list_objects,Scene,utc_time
from ges.download import download_scene,cached_bytes
from ges.storage import load_config,preflight


def main():
    s=s3_client();cfg=load_config();t=utc_time('2020-10-29T16:40:00Z')
    ir=goes_scene(s,t,'goes17',1);start=re.search(r'_s(\d+)_',ir.keys[0]).group(1);selected=[]
    for kind in ['ACMF','ACTPF','ACHAF','CTPF']:
        objects=list_objects(s,'noaa-goes17',f'ABI-L2-{kind}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/')
        matches=[o for o in objects if f'_s{start}_' in o['Key']]
        if len(matches)!=1:raise ValueError('Exact West L2 scan absent/ambiguous')
        selected+=matches
    support=Scene('goes17_cloud_l2','noaa-goes17','',t,tuple(o['Key'] for o in selected),sum(o['Size'] for o in selected),
                  'ABI-L2-ACM-ACTP-ACHA-CTP',tuple(o['Size'] for o in selected))
    scenes=[ir,support];remaining=sum(x.total_bytes-cached_bytes(x,cfg.raw_dir/x.scene_id) for x in scenes)
    print('WEST total',sum(x.total_bytes for x in scenes),'PREFLIGHT',preflight(remaining,cfg.raw_dir,cfg),flush=True)
    for scene in scenes:print('WEST MANIFEST',download_scene(s,scene,cfg.raw_dir,cfg),flush=True)


if __name__=='__main__':main()
