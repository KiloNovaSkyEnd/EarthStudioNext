import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
from ges.storage import load_config
from ges.goni_data import prepare_frame
from ges.range_archive import configure_group_budget


def main():
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=31);p.add_argument('--workers',type=int,default=2);args=p.parse_args()
    cfg=load_config();folder=cfg.processed_dir/'goni_film_v1';m=json.loads((folder/'inventory.json').read_text());items=m['scenes'][:args.limit]
    archived=sum(p.stat().st_size for p in (cfg.raw_dir/'goni_l2_ranges').rglob('*.bin'))
    limit=int(cfg.max_single_scene_gb*1e9)-m['hsd_total_bytes']
    with multiprocessing.Manager() as manager:
        counter=manager.Value('q',archived);lock=manager.Lock()
        print('RANGE GROUP',archived,'/',limit,'bytes',flush=True)
        with ProcessPoolExecutor(max_workers=args.workers,initializer=configure_group_budget,initargs=(counter,lock,limit)) as pool:
            frames=list(pool.map(prepare_frame,items))
    (folder/'frames.json').write_text(json.dumps(frames,indent=2),encoding='utf-8');print('READY',len(frames),flush=True)


if __name__=='__main__':main()
