"""Five-source reference context plus measured GOES-East/West daytime RGB."""
from pathlib import Path
import argparse,json,subprocess
from ges.film_observed import compose_observed

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);args=parser.parse_args()
    folder=ROOT/'data/processed/day_night_v8'
    baseline=ROOT/'data/processed/day_night_v7/earth_day_night.png'
    meta=json.loads(baseline.with_suffix('.json').read_text())
    rgb=[]
    for sat,path in [('goes16',ROOT/'data/processed/day_night_v3/daylight/goes_daylight.png'),
                     ('goes17',folder/'daylight_west/goes_daylight.png')]:
        geometry=next(s['geometry'] for s in meta['night_source']['sources'] if s['provenance']['satellite']==sat)
        rgb.append({'image':str(path.resolve()),'geometry':geometry})
    print('COMPOSING observed RGB and explicit static context',flush=True)
    image=compose_observed(baseline,rgb,ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',
        ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',folder/'earth_day_night.png')
    def run(args):subprocess.run([str(a) for a in args],cwd=ROOT,check=True)
    blend=folder/'blender/earth.blend'
    run([args.blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',image,'--out',blend,'--preview',blend.parent/'earth_4k.png','--preview-width',3840])
    run([args.blender,'--background',blend,'--python-exit-code','1','--python','tests/blender_verify_day_night.py'])


if __name__=='__main__':main()
