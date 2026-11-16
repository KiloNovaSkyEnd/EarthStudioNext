"""Real expanded AHI coverage, uniform L2 policy and independently controlled tint."""
import argparse,json
from pathlib import Path
import numpy as np
from satpy import Scene
from ges.storage import load_config
from ges.catalog import utc_time
from ges.render import observation_interval
from scripts.compare_hinnamnor_geocolor import array,project,sha

ROI=(900,2600,1200,4200)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stamp',choices=['1000','1130'],required=True)
    parser.add_argument('--legacy',action='store_true');args=parser.parse_args();cfg=load_config()
    stamp=utc_time('2022-08-31T'+args.stamp[:2]+':'+args.stamp[2:]+':00Z');root=cfg.processed_dir/'hinnamnor_targeted_v1'
    src=root/args.stamp;src.mkdir(exist_ok=True);r0,r1,c0,c1=ROI
    if not (src/'observed_inputs.npz').exists():
        old=cfg.raw_dir/'hinnamnor_geocolor_v1'/stamp.strftime('%Y%m%dT%H%M%SZ')
        extra=cfg.raw_dir/'hinnamnor_targeted_v1'/stamp.strftime('%Y%m%dT%H%M%SZ')
        files=sorted(p for folder in [old,extra] for p in folder.glob('*.DAT.bz2') if any('_'+b+'_' in p.name for b in ['B03','B07','B13']))
        assert len(files)==12
        scene=Scene(reader='ahi_hsd',filenames=[str(p.resolve()) for p in files]);scene.load(['B03','B07','B13'])
        area=scene['B13'].attrs['area'];crop=area[r0:r1,c0:c1];lo,la=crop.get_lonlats();fields={};bands={}
        for name in ['B07','B13']:
            a=scene[name];assert a.attrs['area']==area and a.attrs['units']=='K'
            fields[name]=array(a.isel(y=slice(r0,r1),x=slice(c0,c1)))
            bands[name]={'units':'K','wavelength':list(a.attrs['wavelength']),'observation_interval_utc':observation_interval(a.attrs)}
        vis=scene['B03'];assert vis.attrs['units']=='%' and vis.attrs['area'].crs==area.crs
        v=vis.data[r0*4:r1*4,c0*4:c1*4]
        fields['B03_fraction_1km']=np.asarray(v.reshape(((r1-r0)*2,2,(c1-c0)*2,2)).mean(axis=(1,3)).compute(num_workers=2),np.float32)/100
        fields['longitude_2km']=lo.astype(np.float32);fields['latitude_2km']=la.astype(np.float32)
        np.savez_compressed(src/'observed_inputs.npz',**fields)
        meta={'kind':'Observed expanded native inputs, no official GeoColor synthesis','nominal_utc':stamp.isoformat(),
              'native_crop_yx':list(ROI),'projection':area.crs.to_dict(),'area_extent_m':list(map(float,crop.area_extent)),
              'output_shape_yx':[(r1-r0)*2,(c1-c0)*2],'bands':bands,
              'finite_fraction':{k:float(np.isfinite(fields[k]).mean()) for k in ['B13','B07','B03_fraction_1km']},
              'input_file_sha256':{str(p.resolve()):sha(p) for p in files}}
        (src/'official_metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    name='expanded_legacy' if args.legacy else 'candidate'
    dest=src/name;dest.mkdir(exist_ok=False)
    project(stamp,dest,source=src,low_cloud_tint_strength=.85,diagnostics=False,
            region_policy='legacy' if args.legacy else 'observed',low_cloud_display='legacy' if args.legacy else 'evidence',
            colour_control=not args.legacy,save_layers=not args.legacy)
    print('READY',args.stamp,name,flush=True)


if __name__=='__main__':main()
