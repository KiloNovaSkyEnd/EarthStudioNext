"""First authentic ABI day + four-source measured IR night sample, no downloads."""
from pathlib import Path
import argparse,json,subprocess,sys
from PIL import Image,ImageDraw
from ges.daylight import render_daylight
from ges.day_night import render_transition,compose_day_night
from ges.blend_night import blend_night

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True)
    parser.add_argument('--out',default='data/processed/day_night_v3');a=parser.parse_args()
    folder=Path(a.out).resolve();width=8192
    day=folder/'daylight/goes_daylight.png'
    if not day.exists():
        cached=ROOT/'data/processed/day_night_v2/daylight'
        if (cached/'goes_daylight.png').exists():
            import shutil
            day.parent.mkdir(parents=True,exist_ok=True)
            for path in cached.glob('goes_daylight*'):shutil.copy2(path,day.parent/path.name)
        else:day=render_daylight(ROOT/'data/raw/goes16_20201029T164018Z/scene.json',day.parent,width)
    sources=json.loads((ROOT/'data/processed/validation_v9/fusion_sources.json').read_text())
    records=[]
    for i,record in enumerate(sources):
        print('TRANSITION IR',i+1,Path(record['image']).parent.name,flush=True)
        target=folder/'transition_sources'/str(i+1)
        existing=list(target.glob('*_transition_ir.png')) if target.exists() else []
        if existing:records.append({**record,'image':str(existing[0])})
        else:records.append(render_transition(record,target,width,supported_twilight=True))
    lights=ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg'
    night=folder/'transition_global/transition_ir.png'
    if not night.exists():blend_night(records,lights,night,'2020-10-29T16:40:00Z')
    composite=compose_day_night(day,night,folder/'earth_day_night.png','2020-10-29T16:40:00Z')
    scene=folder/'blender/earth.blend'
    def run(args):subprocess.run([str(v) for v in args],cwd=ROOT,check=True)
    run([a.blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',composite,'--out',scene,'--preview',scene.parent/'earth_4k.png','--preview-width','3840'])
    run([a.blender,'--background',scene,'--python-exit-code','1','--python','tests/blender_verify_day_night.py'])
    sheet=Image.new('RGB',(2400,490),(12,15,22));draw=ImageDraw.Draw(sheet)
    for i,(name,label) in enumerate([('day_americas_4k.png','Rayleigh-corrected ABI / measured IR gaps'),('terminator_4k.png','CIRA solar transition / measured IR'),('night_asia_4k.png','Accepted supported low-cloud night display')]):
        im=Image.open(scene.parent/name).convert('RGB').resize((800,450),Image.Resampling.LANCZOS)
        sheet.paste(im,(i*800,40));draw.text((i*800+12,12),label+' / 2020-10-29 16:40 UTC',fill='white')
    sheet.save(folder/'day_night_views.png')
    print('OBSERVED DAY/NIGHT SAMPLE',composite,flush=True)


if __name__=='__main__':main()
