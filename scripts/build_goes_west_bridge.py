"""Measured GOES-West bridge; no geographic painting or mask relaxation."""
from pathlib import Path
import json,subprocess,argparse
from ges.cloud_evidence import render_cloud_evidence
from ges.day_night import render_transition
from ges.film_transition import render_vis_cloud,compose_layered
from ges.blend_night import blend_night
from ges.render import create_satpy_scene
from ges.download import read_manifest

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);args=parser.parse_args()
    folder=ROOT/'data/processed/day_night_v6';folder.mkdir(parents=True,exist_ok=True)
    ir=next((ROOT/'data/raw').glob('goes17_20201029T1640*/scene.json'))
    l2=ROOT/'data/raw/goes17_cloud_l2_20201029T164000Z/scene.json';lights=ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg'
    source=folder/'west_source/goes17_evidence_night.png'
    if not source.exists():source=render_cloud_evidence(ir,l2,lights,source.parent,8192)
    m=read_manifest(ir);scene=create_satpy_scene(m['local_files'],'goes17');scene.load(['C13']);area=scene['C13'].attrs['area'];p=area.proj_dict
    record={'image':str(source.resolve()),'geometry':{'longitude':float(p['lon_0']),'latitude':0,
        'altitude_m':float(p['h']),'earth_radius_m':float(area.crs.ellipsoid.semi_major_metre)},
        'geometry_provenance':'Actual GOES17 source projection; no present-day fleet inference'}
    (folder/'west_source_record.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    transition=folder/'west_transition/goes17_transition_ir.png'
    tr={**record,'image':str(transition.resolve())} if transition.exists() else render_transition(record,transition.parent,8192,supported_twilight=True)
    nm=json.loads((ROOT/'data/processed/day_night_v3/transition_global/transition_ir.json').read_text())
    records=[{k:s[k] for k in ['image','geometry','geometry_provenance'] if k in s} for s in nm['sources']]+[tr]
    night=folder/'transition_global/transition_ir.png'
    if not night.exists():blend_night(records,lights,night,'2020-10-29T16:40:00Z')
    paths=sorted((ROOT/'data/processed/day_night_v5/visible_sources').glob('*_vis_alpha.png'))
    vis=folder/'visible_sources/goes17_vis_alpha.png'
    if not vis.exists():vis=render_vis_cloud(record,vis.parent)
    paths.append(vis)
    result=compose_layered(paths,night,ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',lights,
        folder/'earth_day_night.png','2020-10-29T16:40:00Z')
    def run(arguments):subprocess.run([str(x) for x in arguments],cwd=ROOT,check=True)
    blend=folder/'blender/earth.blend'
    run([args.blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',result,'--out',blend,'--preview',blend.parent/'earth_4k.png','--preview-width',3840])
    run([args.blender,'--background',blend,'--python-exit-code','1','--python','tests/blender_verify_day_night.py'])
    print('WEST BRIDGE RENDERED',result,flush=True)


if __name__=='__main__':main()
