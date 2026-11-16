"""Inventory-only Hinnamnor archive/track/solar research; never fetch satellite bodies.

S3 LIST/HEAD only. Small official best-track ZIP has a separate 2MB cap and atomic save.
All outputs use a new directory, not existing Goni inputs or renderer outputs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import zipfile

import numpy as np
from pyproj import Proj
import requests
from ges.catalog import s3_client, list_objects, utc_time
from ges.solar import solar_weights
from ges.storage import load_config

TRACK_URL='https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip'
START=utc_time('2022-08-31T06:00:00Z')
END=utc_time('2022-09-01T04:00:00Z')


def write_csv(path, rows):
    with path.open('x',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def best_track(text):
    lines=text.splitlines()
    i=next(i for i,line in enumerate(lines) if line.startswith('66666 2211'))
    header=lines[i]; count=int(header.split()[2]); rows=[]
    for line in lines[i+1:i+1+count]:
        parts=line.split()
        rows.append({'utc':datetime.strptime(parts[0],'%y%m%d%H').replace(tzinfo=timezone.utc).isoformat(),
                     'latitude':int(parts[3])/10,'longitude':int(parts[4])/10,
                     'pressure_hpa':int(parts[5]),'wind_kt':int(parts[6]),'raw_line':line})
    return header, rows


def interpolate(rows, stamp):
    times=np.array([utc_time(r['utc']).timestamp() for r in rows])
    assert times[0]<=stamp.timestamp()<=times[-1]
    return tuple(float(np.interp(stamp.timestamp(),times,[r[k] for r in rows])) for k in ['longitude','latitude'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    cfg=load_config(); queried=datetime.now(timezone.utc).isoformat()
    protected={str(p):[p.stat().st_size,p.stat().st_mtime_ns] for base in [cfg.raw_dir,cfg.export_dir]
               for p in base.rglob('*') if p.is_file()}
    code={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('ges').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    # Search configured archive, processed caches and permanent outputs before network access.
    cached=[]; local_by_name={}
    for root in [cfg.raw_dir,cfg.processed_dir,cfg.export_dir]:
        for p in root.rglob('*'):
            if not p.is_file():continue
            local_by_name.setdefault(p.name,[]).append(p)
            if any(v in str(p).lower() for v in ['hinnamnor','20220831','20220901','2022243','2022244']):
                if args.out.parent not in p.parents:cached.append({'path':str(p),'bytes':p.stat().st_size})
    (args.out/'local_cache.json').write_text(json.dumps({'configured_roots':[str(cfg.raw_dir),str(cfg.processed_dir),str(cfg.export_dir)],'matches':cached},indent=2),encoding='utf-8')
    response=requests.head(TRACK_URL,timeout=30); response.raise_for_status()
    size=int(response.headers['Content-Length']); assert 0<size<=2_000_000
    received=requests.get(TRACK_URL,timeout=60,headers={'Accept-Encoding':'identity'});received.raise_for_status()
    assert len(received.content)==size
    partial=args.out/'best_track.zip.part';partial.write_bytes(received.content);partial.rename(args.out/'best_track.zip')
    with zipfile.ZipFile(io.BytesIO(received.content)) as archive:
        text=archive.read('bst_all.txt').decode('ascii')
    header,track=best_track(text)
    (args.out/'hinnamnor_best_track.json').write_text(json.dumps({'url':TRACK_URL,'bytes':size,
        'zip_sha256':hashlib.sha256(received.content).hexdigest(),'header':header,'track':track},indent=2),encoding='utf-8')
    relevant=[r for r in track if START<=utc_time(r['utc'])<=END+timedelta(hours=2)]
    write_csv(args.out/'track.csv',relevant)
    # Derive regional vertical strips from a declared geographic ROI, not Goni constants.
    roi=[118.,14.,142.,36.]
    projection=Proj(proj='geos',lon_0=140.7,h=35785863,a=6378137,b=6356752.3,sweep='y')
    lo,la=np.meshgrid(np.linspace(roi[0],roi[2],101),np.linspace(roi[1],roi[3],101))
    x,y=projection(lo,la); rows=(5_500_000-y)/2000
    segments=sorted(set((rows.astype(int)//550+1).ravel().tolist()))
    assert segments==[2,3,4]
    # Solar along the interpolated best track and across the fixed ROI.
    times=[START+timedelta(minutes=10*i) for i in range(133)]
    solar=[]
    for stamp in times:
        lon,lat=interpolate(track,stamp); center=float(solar_weights(stamp,lon,lat).elevation_deg)
        field=solar_weights(stamp,lo,la).elevation_deg
        solar.append({'nominal_utc':stamp.isoformat(),'center_longitude_interpolated':lon,'center_latitude_interpolated':lat,
                      'center_solar_elevation_deg':center,'roi_solar_min_deg':float(field.min()),'roi_solar_max_deg':float(field.max()),
                      'position_is_interpolated':True})
    write_csv(args.out/'solar_10min.csv',solar)
    crossings=[]
    for a,b in zip(solar,solar[1:]):
        for level in [-6,0,6]:
            va,vb=[r['center_solar_elevation_deg']-level for r in [a,b]]
            if va*vb<0:
                stamp=utc_time(a['nominal_utc'])+timedelta(seconds=600*(-va)/(vb-va))
                crossings.append({'threshold_deg':level,'utc_approx':stamp.isoformat(),
                                  'direction':'sunrise' if vb>va else 'sunset'})
    s3=s3_client();bucket='noaa-himawari8'
    l2_objects=[]
    for day in [START,END]:
        l2_objects+=list_objects(s3,bucket,day.strftime('AHI-L2-FLDK-Clouds/%Y/%m/%d/'))
    def collect(stamp):
        objects=list_objects(s3,bucket,stamp.strftime('AHI-L1b-FLDK/%Y/%m/%d/%H%M/'))
        result=[]
        for band in ['B03','B07','B13']:
            matches=[o for o in objects if f'_{band}_FLDK_' in o['Key']]
            for seg in range(1,11):
                selected=[o for o in matches if f'_S{seg:02d}10.' in o['Key']]
                if len(selected)==1:
                    result.append(object_row(selected[0],stamp,band,seg,'HSD'))
                else:
                    result.append({'nominal_utc':stamp.isoformat(),'kind':'HSD','band_or_product':band,'segment':seg,
                                   'key':'','bytes':0,'etag':'','last_modified_utc':'','regional':seg in segments,'cached_size_verified':False,
                                   'filename_start_utc':'','filename_end_utc':'','status':'missing_or_ambiguous'})
        for kind in ['CMSK','CHGT','CPHS']:
            selected=[o for o in l2_objects if stamp.strftime('/%Y/%m/%d/%H%M/') in o['Key'] and f'AHI-{kind}_' in o['Key']]
            if len(selected)!=1:
                result.append({'nominal_utc':stamp.isoformat(),'kind':'L2','band_or_product':kind,'segment':0,
                               'key':'','bytes':0,'etag':'','last_modified_utc':'','regional':False,'cached_size_verified':False,
                               'filename_start_utc':'','filename_end_utc':'','status':'missing_or_ambiguous'})
            else:result.append(object_row(selected[0],stamp,kind,0,'L2'))
        return result
    def object_row(obj,stamp,band,segment,kind):
        name=Path(obj['Key']).name; start=end=''
        match=re.search(r'_s(\d{14})(\d)_e(\d{14})(\d)_',name)
        if match:
            start=datetime.strptime(match[1],'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc,microsecond=int(match[2])*100000).isoformat()
            end=datetime.strptime(match[3],'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc,microsecond=int(match[4])*100000).isoformat()
        return {'nominal_utc':stamp.isoformat(),'kind':kind,'band_or_product':band,'segment':segment,
                'key':obj['Key'],'bytes':obj['Size'],'etag':obj['ETag'],'last_modified_utc':obj['LastModified'].isoformat(),
                'regional':segment in segments,'cached_size_verified':any(p.stat().st_size==obj['Size'] for p in local_by_name.get(name,[])),
                'filename_start_utc':start,'filename_end_utc':end,'status':'listed'}
    with ThreadPoolExecutor(max_workers=5) as pool:
        batches=list(pool.map(collect,times))
    objects=[o for batch in batches for o in batch]
    write_csv(args.out/'archive_files_22h.csv',objects)
    summaries=[]
    for stamp,batch in zip(times,batches):
        summaries.append({'nominal_utc':stamp.isoformat(),'hsd_full_bytes':sum(o['bytes'] for o in batch if o['kind']=='HSD'),
                          'hsd_regional_bytes':sum(o['bytes'] for o in batch if o['kind']=='HSD' and o['regional']),
                          'l2_whole_bytes':sum(o['bytes'] for o in batch if o['kind']=='L2'),
                          'missing_l2':','.join(o['band_or_product'] for o in batch if o['kind']=='L2' and o['status']!='listed'),
                          'missing_hsd':','.join(o['band_or_product']+':S'+str(o['segment']) for o in batch if o['kind']=='HSD' and o['status']!='listed')})
    write_csv(args.out/'scan_summary.csv',summaries)
    # Representative HEAD verification (no GET of imagery).
    heads=[]
    for band in ['B03','B07','B13','CMSK','CHGT','CPHS']:
        obj=next(o for o in objects if o['band_or_product']==band and o['nominal_utc']==utc_time('2022-08-31T09:00:00Z').isoformat())
        h=s3.head_object(Bucket=bucket,Key=obj['key']);assert h['ContentLength']==obj['bytes'] and h['ETag']==obj['etag']
        heads.append({'key':obj['key'],'content_length':h['ContentLength'],'etag':h['ETag'],
                      'http_status':h['ResponseMetadata']['HTTPStatusCode']})
    protected_unchanged=all(Path(p).exists() and [Path(p).stat().st_size,Path(p).stat().st_mtime_ns]==v for p,v in protected.items())
    sources_unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==v for p,v in code.items())
    assert protected_unchanged and sources_unchanged
    report={'queried_utc':queried,'bucket':bucket,'window':[START.isoformat(),END.isoformat()],
            'scans':len(times),'objects':len(objects),'local_cache_matches':cached,
            'total_bytes_by_kind':{kind:sum(o['bytes'] for o in objects if o['kind']==kind) for kind in ['HSD','L2']},
            'regional_hsd_bytes_all_22h':sum(o['bytes'] for o in objects if o['kind']=='HSD' and o['regional']),
            'missing_l2_scans':[r for r in summaries if r['missing_l2']],
            'missing_hsd_scans':[r for r in summaries if r['missing_hsd']],
            'roi_wsen':roi,'nominal_projection_row_bounds_2km':[float(rows.min()),float(rows.max())],
            'regional_hsd_segments':segments,'projection_note':'Nominal geos geometry; validate exact HSD header offsets and crop before download/processing.',
            'sun_crossings_interpolated':crossings,'heads':heads,'track_metadata_bytes':size,
            'satellite_body_downloaded_bytes':0,'configured_single_scene_limit_gb':cfg.max_single_scene_gb,
            'disk_free_bytes':shutil.disk_usage(cfg.raw_dir).free,'reserve_gb':cfg.reserve_free_gb,
            'protected_file_count':len(protected),'protected_size_mtime_unchanged':protected_unchanged,
            'ges_sha256_unchanged':sources_unchanged,'ges_sha256':code,
            'limits':'LIST/HEAD proves object availability/size, not calibrated content or meteorological quality. '
                     'L2 variable schema and same-scan compatibility remain unverified until bounded pilot read. '
                     'JMA positions linearly interpolated for solar, not observed 10-minute fixes; geometric sun excludes refraction. '
                     'Filename L2 start/end not assumed full L1 HSD scan intervals; inspect raw headers later.'}
    (args.out/'archive_verification.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['ges_sha256','heads','local_cache_matches','missing_l2_scans']},indent=2,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
