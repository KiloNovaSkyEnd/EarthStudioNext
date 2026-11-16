"""Calibrate actual bounded AHI scans and reuse the validated cloud material, no synthetic observations."""
import argparse
import json
from pathlib import Path
import numpy as np
from satpy import Scene
from ges.catalog import utc_time
from ges.storage import load_config
from ges.render import observation_interval
from scripts.compare_hinnamnor_geocolor import project,R0,R1,C0,C1,array,sha


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stamp',required=True);args=p.parse_args()
    stamp=utc_time(args.stamp);cfg=load_config();root=cfg.processed_dir/'hinnamnor_ocean_v1';dest=root/stamp.strftime('%H%M')
    dest.mkdir(exist_ok=True);assert not (dest/'material_metadata.json').exists(),'Do not overwrite completed material'
    if stamp.strftime('%H%M')=='1000':
        source=cfg.processed_dir/'hinnamnor_geocolor_v1/1000'
    else:
        source=dest;files=sorted((cfg.raw_dir/'hinnamnor_ocean_v1'/stamp.isoformat().replace('-','').replace(':','')).glob('*.DAT.bz2'));assert len(files)==9
        scene=Scene(reader='ahi_hsd',filenames=[str(f.resolve()) for f in files]);scene.load(['B03','B07','B13'])
        ir=scene['B13'];assert ir.shape==(5500,5500) and ir.attrs['units']=='K'
        base=ir.attrs['area'];area=base[R0:R1,C0:C1];lo,la=area.get_lonlats();raw={};bands={}
        for band in ['B07','B13']:
            data=scene[band];assert data.attrs['units']=='K' and data.attrs['area']==base
            raw[band]=array(data.isel(y=slice(R0,R1),x=slice(C0,C1)))
            bands[band]={'units':'K','wavelength':list(data.attrs['wavelength']),'observation_interval_utc':observation_interval(data.attrs)}
        vis=scene['B03'];assert vis.attrs['units']=='%' and vis.shape==(22000,22000)
        assert vis.attrs['area'].crs==base.crs and np.allclose(vis.attrs['area'].area_extent,base.area_extent,atol=.1)
        values=vis.data[R0*4:R1*4,C0*4:C1*4]
        raw['B03_fraction_1km']=np.asarray(values.reshape(((R1-R0)*2,2,(C1-C0)*2,2)).mean(axis=(1,3)).compute(num_workers=2),np.float32)/100
        raw['longitude_2km']=lo.astype(np.float32);raw['latitude_2km']=la.astype(np.float32)
        # Actual missing detector pixels remain NaN; never fill observations to
        # satisfy a display test. Record band coverage for temporal review.
        assert np.isfinite(raw['B13']).any() and np.isfinite(raw['B07']).any()
        np.savez_compressed(dest/'observed_inputs.npz',**raw)
        metadata={'kind':'Calibrated native inputs only, not an official GeoColor output','nominal_utc':stamp.isoformat(),
                  'projection':base.crs.to_dict(),'area_extent_m':list(map(float,area.area_extent)),
                  'output_shape_yx':[(R1-R0)*2,(C1-C0)*2],'bands':bands,
                  'finite_coverage_fraction':{k:float(np.isfinite(raw[k]).mean()) for k in ['B13','B07','B03_fraction_1km']},
                  'input_file_sha256':{str(f.resolve()):sha(f) for f in files}}
        (dest/'official_metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    project(stamp,dest,source=source,low_cloud_tint_strength=.85,diagnostics=False)
    (dest/'source_location.json').write_text(json.dumps({'source_directory':str(source.resolve()),'observation_utc':stamp.isoformat()},indent=2),encoding='utf-8')
    print('OBSERVED MATERIAL READY',stamp.isoformat(),flush=True)


if __name__=='__main__':main()
