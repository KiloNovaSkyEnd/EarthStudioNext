"""Measured VIS cloud layers, independent static ground, C2 solar transition."""
from pathlib import Path
import argparse,json,subprocess
from PIL import Image,ImageDraw
from ges.film_transition import render_vis_cloud,compose_layered

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);a=parser.parse_args()
    out=ROOT/'data/processed/day_night_v5';out.mkdir(parents=True,exist_ok=True)
    records=json.loads((ROOT/'data/processed/validation_v9/fusion_sources.json').read_text());paths=[]
    for i in [0,1,2,3]:
        record=records[i];sat=json.loads(Path(record['image']).with_suffix('.json').read_text())['satellite']
        p=out/'visible_sources'/(sat+'_vis_alpha.png')
        print('MEASURED VISIBLE',sat,flush=True)
        if not p.exists():p=render_vis_cloud(record,p.parent,vis_manifest=ROOT/'data/raw/visible/himawari8_20201029T164000Z/scene.json' if i==0 else None)
        paths.append(p)
    p=compose_layered(paths,ROOT/'data/processed/day_night_v3/transition_global/transition_ir.png',
        ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',
        out/'earth_day_night.png','2020-10-29T16:40:00Z')
    def run(args):subprocess.run([str(x) for x in args],cwd=ROOT,check=True)
    scene=out/'blender/earth.blend'
    run([a.blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',p,'--out',scene,'--preview',scene.parent/'earth_4k.png','--preview-width',3840])
    run([a.blender,'--background',scene,'--python-exit-code','1','--python','tests/blender_verify_day_night.py'])
    sheet=Image.new('RGB',(2400,3*715),(10,14,22));draw=ImageDraw.Draw(sheet)
    for i,name in enumerate(['day_americas_4k.png','terminator_4k.png','night_asia_4k.png']):
        for col,version in enumerate(['day_night_v3','day_night_v5']):
            im=Image.open(ROOT/'data/processed'/version/'blender'/name).convert('RGB');im.thumbnail((1200,675),Image.Resampling.LANCZOS)
            sheet.paste(im,(col*1200,i*715+40));draw.text((col*1200+12,i*715+12),version+' / '+name+' / 2020-10-29 16:40 UTC',fill='white')
    sheet.save(out/'twilight_before_after.png');print('LAYERED TWILIGHT READY',p,flush=True)


if __name__=='__main__':main()
