"""Fetch exactly ten authentic AHI B03 segments, preserving existing IR manifest."""
from ges.catalog import s3_client,himawari_scene,utc_time
from ges.download import download_scene
from ges.storage import load_config


def main():
    cfg=load_config();client=s3_client()
    scene=himawari_scene(client,utc_time('2020-10-29T16:40:00Z'),('B03',),0)
    print('AHI B03 listed bytes',scene.total_bytes,'segments',len(scene.keys),flush=True)
    print(download_scene(client,scene,cfg.raw_dir/'visible',cfg),flush=True)


if __name__=='__main__':main()
