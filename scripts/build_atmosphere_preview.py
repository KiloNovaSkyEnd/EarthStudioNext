"""Render optional effects separately from the verified nonpolar observations."""
from pathlib import Path
import argparse,json,subprocess
from ges.visual_effects import atmosphere_config,validate_atmosphere

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);args=parser.parse_args()
    source=ROOT/'data/processed/day_night_v9/earth_day_night.png'
    meta=json.loads(source.with_suffix('.json').read_text());folder=ROOT/'data/processed/atmosphere_v1'
    folder.mkdir(parents=True,exist_ok=True)
    config=validate_atmosphere(atmosphere_config(meta['reference_utc'],day=True,airglow=True),meta['reference_utc'])
    path=folder/'atmosphere_config.json';path.write_text(json.dumps(config,indent=2),encoding='utf-8')
    def run(arguments):subprocess.run([str(a) for a in arguments],cwd=ROOT,check=True)
    blend=folder/'earth_optional_atmosphere.blend'
    run([args.blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',source,'--out',blend,'--atmosphere-config',path])
    run([args.blender,'--background',blend,'--python-exit-code','1','--python','tests/blender_verify_atmosphere.py'])


if __name__=='__main__':main()
