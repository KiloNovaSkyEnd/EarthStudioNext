"""A separately budgeted real3.9um supplement needed to restore night texture."""
from concurrent.futures import ThreadPoolExecutor
import json
from ges.catalog import s3_client,list_objects,Scene,utc_time
from ges.download import download_scene,cached_bytes
from ges.storage import load_config,preflight


def main():
    cfg=load_config();folder=cfg.processed_dir/'goni_film_v1';inv=json.loads((folder/'inventory.json').read_text());s3=s3_client()
    def plan(item):
        stamp=utc_time(item['nominal_utc']);prefix=stamp.strftime('AHI-L1b-FLDK/%Y/%m/%d/%H%M/')
        objects=list_objects(s3,'noaa-himawari8',prefix);selected=[]
        for segment in [3,4,5]:
            matches=[v for v in objects if '_B07_FLDK_' in v['Key'] and f'_S{segment:02d}10.' in v['Key']]
            if len(matches)!=1:raise ValueError('Exact shortwave acquisition/segment absent')
            selected+=matches
        return Scene('himawari8_goni_shortwave','noaa-himawari8',prefix,stamp,tuple(v['Key'] for v in selected),sum(v['Size'] for v in selected),
                     'AHI-HSD-regional-B07-supplement',tuple(v['Size'] for v in selected))
    with ThreadPoolExecutor(max_workers=6) as pool:scenes=list(pool.map(plan,[m for m in inv['scenes'] if utc_time(m['nominal_utc']).hour>=7]))
    total=sum(s.total_bytes for s in scenes);cached=sum(cached_bytes(s,cfg.raw_dir/s.scene_id) for s in scenes)
    # This is a new, required band supplement, not an increase to the old
    # HSD+L2 range cap. Original objects and all retained pilot ranges remain.
    if total>500_000_000:raise RuntimeError('Shortwave supplement exceeds explicit500MB batch ceiling')
    check=preflight(total,cfg.raw_dir,cfg,existing_bytes=cached)
    doc={'purpose':'Restore observed longwave/shortwave night-low-cloud texture previously omitted',
         'batch_limit_bytes':500_000_000,'total_bytes':total,'new_bytes':total-cached,'preflight':check,'is_additional_to_original_batch':True,
         'band':'AHI B07 3.9um calibrated brightness temperature; spectral display only when both actual-scan endpoints solar elevation<=-6deg',
         'scenes':[{'nominal_utc':s.observed_utc.isoformat(),'manifest':str((cfg.raw_dir/s.scene_id/'scene.json').resolve())} for s in scenes]}
    (folder/'shortwave_inventory.json').write_text(json.dumps(doc,indent=2),encoding='utf-8');print('SHORTWAVE PREFLIGHT',total,'new',total-cached,flush=True)
    def fetch(scene):
        download_scene(s3,scene,cfg.raw_dir,cfg);print('SHORTWAVE RAW',scene.observed_utc.isoformat(),flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(fetch,scenes))
    print('SHORTWAVE READY',len(scenes),flush=True)


if __name__=='__main__':main()
