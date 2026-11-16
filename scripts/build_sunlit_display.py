"""Recompose the verified five-source scene with a brighter daylight display."""
from pathlib import Path
import argparse,json,subprocess,sys
from ges.film_transition import compose_layered

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);args=parser.parse_args()
    baseline=ROOT/'data/processed/day_night_v6/earth_day_night.json'
    meta=json.loads(baseline.read_text());folder=ROOT/'data/processed/day_night_v7'
    result=compose_layered([s['image'] for s in meta['day_sources']],meta['night_image'],
        ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',
        ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',folder/'earth_day_night.png',
        meta['reference_utc'],daylight_profile='sunlit-v1')
    def run(args):subprocess.run([str(a) for a in args],cwd=ROOT,check=True)
    blend=folder/'blender/earth.blend'
    run([args.blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',result,'--out',blend,'--preview',blend.parent/'earth_4k.png','--preview-width',3840])
    run([args.blender,'--background',blend,'--python-exit-code','1','--python','tests/blender_verify_day_night.py'])
    run([sys.executable,'-m','scripts.verify_global_twilight','--out',folder])


if __name__=='__main__':main()
