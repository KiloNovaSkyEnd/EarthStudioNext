"""Build the observed-overlap globe and real-scene visual QA report."""
import argparse,json,subprocess,sys
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from ges.blend_night import blend_night,grazing_alpha
from ges.cloud_evidence import LOW_CLASSES

ROOT=Path(__file__).resolve().parents[1]


def finish(blender,output=None,grazing_guard=False):
    folder=Path(output).resolve() if output else ROOT/'data/processed/validation_v9'
    matrix=json.loads((folder/'validation_matrix.json').read_text())
    checks=[]
    for row in matrix:
        path=ROOT/row['texture'];meta=json.loads(path.with_suffix('.json').read_text())
        a=np.asarray(Image.open(path));c=np.asarray(Image.open(path.parent/meta['cloud_evidence_classes']))
        n=np.asarray(Image.open(path.with_name(path.stem+'_eligible.png')))>0
        cov=np.asarray(Image.open(path.parent/meta['source_ir_coverage']))>0
        blue=(a[...,2]>a[...,0])&(a[...,3]>0)
        assert not (blue&~np.isin(c,LOW_CLASSES)).any()
        assert not (a[...,3][~n]>0).any() and not (a[...,3][~cov]>0).any()
        probe=json.loads((ROOT/row['blender_scene']).with_name('verification.json').read_text())
        color=[r for r in probe['checks'] if r['name']=='CloudTextureProbe']
        assert len(color)==1 and color[0]['max_rgb_error']<.04
        checks.append({'case':row['case'],'blue_pixels':int(blue.sum()),
                       'blue_class_counts':{str(v):int((blue&(c==v)).sum()) for v in LOW_CLASSES},
                       'unsupported_blue':0,'opacity_outside_night_or_coverage':0,
                       'globe_cloud_rgb_max_error':color[0]['max_rgb_error'],
                       'independent_cloud_accuracy_validation':False})
    (folder/'pixel_and_globe_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    geometry=json.loads((ROOT/'data/processed/seam_blend_v1/geometry.json').read_text())
    # The unchanged daytime-gated 16:40 ABI diagnostic may be reused; it has
    # zero night opacity and cannot be affected by supported-low visibility.
    goes_day=folder/'goes16_1640/goes16_evidence_night.png'
    if not goes_day.exists():goes_day=ROOT/'data/processed/validation_v5/goes16_1640/goes16_evidence_night.png'
    files=[folder/'himawari8_1640/ahi_evidence_night.png',goes_day,
           folder/'meteosat_msg4_supported_v2/meteosat_msg4_evidence_night.png',
           folder/'meteosat_msg1_supported_v2/meteosat_msg1_evidence_night.png']
    navigation=[json.loads(p.with_suffix('.json').read_text()).get('navigation_recipe') for p in files]
    if any(v=='inverse-native-geos-pixel-footprint-v1' for v in navigation):
        if not all(v=='inverse-native-geos-pixel-footprint-v1' for v in navigation):
            raise ValueError('Native-navigation validation requires all four native-navigation inputs, including daytime GOES16; do not reuse legacy KD coverage')
    records=[{**r,'image':str(p)} for r,p in zip(geometry,files)]
    (folder/'fusion_sources.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    target=blend_night(records,ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',
                       folder/'global/global_night.png','2020-10-29T16:40:00Z',
                       grazing_guard=grazing_guard)
    # Verify union and all single-source RGBA against source observations.
    count=np.asarray(Image.open(target.with_name(target.stem+'_observation_count.png')))
    result=np.asarray(Image.open(target));union=np.zeros(count.shape,dtype=bool)
    exact=0
    guard=grazing_guard
    for p,record in zip(files,records):
        m=json.loads(p.with_suffix('.json').read_text());mask=np.asarray(Image.open(p.parent/m['source_ir_coverage']))>0
        union|=mask;only=mask&(count==1);source=np.asarray(Image.open(p))
        if guard:
            source=source.copy();hh,ww=source.shape[:2];lon=-180+(np.arange(ww)+.5)*360/ww
            for r in range(0,hh,128):
                sl=slice(r,min(r+128,hh));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/ww
                source[sl]=grazing_alpha(source[sl],lon[None,:],lat[:,None],record['geometry'])
        assert np.array_equal(result[only],source[only]);exact+=int(only.sum())
    outputcov=np.asarray(Image.open(target.with_name(target.stem+'_coverage.png')))>0
    assert np.array_equal(union,outputcov);assert not result[...,3][~union].any()
    (target.parent/'verification.json').write_text(json.dumps({'observed_union_exact':True,
        ('single_source_after_declared_limb_alpha_exact_pixels' if guard else 'single_source_rgba_exact_pixels'):exact,
        'grazing_display_guard_enabled':guard,'opacity_outside_observed_union':0,
        'is_cloud_accuracy_validation':False},indent=2),encoding='utf-8')
    scene=folder/'blender/global/earth.blend'
    def run(args):subprocess.run([str(a) for a in args],cwd=ROOT,check=True)
    run([blender,'--background','--factory-startup','--python-exit-code','1','--python','blender_make_earth.py','--',
         '--cloud',target,'--night-reference',target.with_name(target.stem+'_surface.png'),'--out',scene,
         '--preview',scene.parent/'earth_4k.png','--preview-width','3840'])
    run([blender,'--background',scene,'--python-exit-code','1','--python','tests/blender_verify.py','--','--nairobi-covered'])
    # Consistent camera and scale within each sensor's temporal pair.
    sheet=Image.new('RGB',(1600,1470),(12,15,22));draw=ImageDraw.Draw(sheet)
    for i,row in enumerate(matrix):
        stem='night_pacific_closeup.png' if row['case'].startswith('himawari') else 'night_americas_closeup.png' if row['case'].startswith('goes') else 'night_regional_closeup.png'
        image=Image.open((ROOT/row['blender_scene']).parent/stem).convert('RGB').resize((800,450),Image.Resampling.LANCZOS)
        x=(i%2)*800;y=(i//2)*490;sheet.paste(image,(x,y+40))
        labels={'himawari8_1640':'Himawari-8 2020-10-29 16:40 UTC',
                'himawari8_1740':'Himawari-8 2020-10-29 17:40 UTC',
                'goes16_0640':'GOES-16 2020-10-29 06:40 UTC',
                'goes16_0740':'GOES-16 2020-10-29 07:40 UTC',
                'meteosat_msg4':'Meteosat-11 2020-10-29 16:30 UTC / height-based',
                'meteosat_msg1':'Meteosat-8 2020-10-29 16:30 UTC / height-based'}
        draw.text((x+12,y+12),labels[row['case']],fill=(235,240,255))
    sheet.save(folder/'cross_time_globe_comparison.png')
    print('VALIDATION REPORT',folder/'pixel_and_globe_checks.json',flush=True)
    print('GLOBAL BLENDED GLOBE',scene,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output')
    p.add_argument('--grazing-guard',action='store_true',help='Experimental stronger alpha guard; rejected for the current scene due to high-latitude dark band')
    a=p.parse_args();finish(a.blender,a.output,a.grazing_guard)
