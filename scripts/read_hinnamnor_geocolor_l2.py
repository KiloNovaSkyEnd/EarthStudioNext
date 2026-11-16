"""Experiment-only 2022 L2 schema validation and bounded ROI extraction; no production adapter edits."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import h5py
import numpy as np
from ges.catalog import s3_client,utc_time
from ges.goni_data import decode
from ges.range_archive import RangeArchive
from ges.storage import load_config,preflight
from scripts.compare_hinnamnor_geocolor import R0,R1,C0,C1


def serial(value):
    if isinstance(value,(bytes,np.bytes_)):return value.decode(errors='replace')
    if isinstance(value,np.ndarray):return [serial(v) for v in value.tolist()] if value.ndim else serial(value.item())
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,(list,tuple)):return [serial(v) for v in value]
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stamp',required=True)
    parser.add_argument('--out',type=Path);parser.add_argument('--raw',type=Path);parser.add_argument('--ranges',type=Path)
    parser.add_argument('--native-roi',nargs=4,type=int,default=[R0,R1,C0,C1])
    args=parser.parse_args()
    stamp=utc_time(args.stamp);cfg=load_config();out=args.out or cfg.processed_dir/'hinnamnor_geocolor_v1'
    r0,r1,c0,c1=args.native_roi
    assert 0<=r0<r1<=5500 and 0<=c0<c1<=5500
    dest=out/stamp.strftime('%H%M');dest.mkdir(exist_ok=True)
    plan=json.loads((out/'download_plan.json').read_text())
    selected=[r for r in plan['files'] if r['kind']=='L2' and utc_time(r['nominal_utc'])==stamp]
    root=(args.raw or cfg.raw_dir/'hinnamnor_geocolor_v1')/stamp.strftime('%Y%m%dT%H%M%SZ')
    caps={'CMSK':50_000_000,'CHGT':120_000_000,'CPHS':50_000_000}
    preflight(sum(caps.values()),cfg.raw_dir,cfg)
    fields={};records=[];client=s3_client()
    for record in selected:
        kind=next(k for k in caps if 'AHI-'+k in record['key'])
        whole=root/Path(record['key']).name
        stream=None
        if whole.exists():assert whole.stat().st_size==record['bytes'];source=whole
        else:
            stream=RangeArchive(client,'noaa-himawari8',record['key'],record['bytes'],record['etag'],
                                (args.ranges or cfg.raw_dir/'hinnamnor_geocolor_l2_ranges')/stamp.strftime('%H%M')/kind,
                                cfg,max_bytes=caps[kind],block_size=65536)
            source=stream
        with nullcontext() if stream is None else stream:
            with h5py.File(source,'r') as f:
                attrs={k:serial(v) for k,v in f.attrs.items()}
                assert attrs['satellite_name']=='Himawari-8' and attrs['instrument_name']=='AHI'
                start=utc_time(attrs['time_coverage_start']);end=utc_time(attrs['time_coverage_end'])
                assert stamp<=start<stamp.replace(second=0)+__import__('datetime').timedelta(minutes=1)
                assert start<=end<stamp+__import__('datetime').timedelta(minutes=10)
                quality=int(np.asarray(f['granule_level_quality_flag'][()]).ravel()[0]);assert quality==0
                names={'CMSK':['CloudMask','CloudMaskQualFlag','CloudProbability'],
                       'CHGT':['CldTopHght','ZcError','CloudHgtQF'],
                       'CPHS':['CloudPhase','CloudPhaseFlag']}[kind]
                descriptions={}
                for name in names:
                    v=f[name];assert v.shape[:2]==(5500,5500)
                    if name in ['CldTopHght','ZcError']:assert serial(v.attrs['units'])=='Meter'
                    selection=np.s_[r0:r1,c0:c1,0] if v.ndim==3 else np.s_[r0:r1,c0:c1]
                    fields[name]=decode(v,selection,stream)
                    descriptions[name]={'shape':list(v.shape),'chunks':v.chunks,'dtype':str(v.dtype),
                                        'attrs':{k:serial(val) for k,val in v.attrs.items() if not k.startswith('_Netcdf') and k!='DIMENSION_LIST'}}
                # Embedded navigation is checked against independently calibrated HSD area after A is ready.
                nav=[]
                for row,col in [(1100,1800),(1500,2200),(1900,2800)]:
                    nav.append({'row':row,'column':col,'longitude':float(f['Longitude'][row,col]),'latitude':float(f['Latitude'][row,col])})
                audit=stream.audit() if stream else {'archive':str(whole.resolve()),'is_complete_raw_file':True,'new_bytes_this_run':0,'remote_bytes':record['bytes']}
                records.append({**record,'product':kind,'native_crop_yx':[r0,r1,c0,c1],'global_attrs':attrs,'fields':descriptions,'navigation':nav,'range_audit':audit})
        print('L2 ROI VERIFIED',stamp.isoformat(),kind,audit,flush=True)
    assert len(records)==3
    np.savez_compressed(dest/'l2_observed_roi.npz',**fields)
    (dest/'l2_schema.json').write_text(json.dumps(records,indent=2),encoding='utf-8')


if __name__=='__main__':main()
