"""Recompose the cached nonpolar observations; no polar data or downloads."""
from pathlib import Path
import argparse,subprocess
from ges.film_singlepass import compose_singlepass

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);args=parser.parse_args()
    folder=ROOT/'data/processed/day_night_v9'
    image=compose_singlepass(ROOT/'data/processed/day_night_v8/earth_day_night.png',folder/'earth_day_night.png')
    def run(args):subprocess.run([str(a) for a in args],cwd=ROOT,check=True)
    blend=folder/'blender/earth.blend'
    run([args.blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',image,'--out',blend,'--preview',blend.parent/'earth_4k.png','--preview-width',3840])
    run([args.blender,'--background',blend,'--python-exit-code','1','--python','tests/blender_verify_day_night.py'])


if __name__=='__main__':main()
