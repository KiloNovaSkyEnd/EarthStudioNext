"""Offline budget/validation summary from saved S3 listing and decoded reference evidence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from datetime import timedelta

import numpy as np
from PIL import Image
from pyorbital import astronomy
from ges.catalog import utc_time
from ges.solar import solar_weights
from scripts.research_hinnamnor_archive import best_track, interpolate, write_csv


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve();archive=root/'archive_complete'
    report=json.loads((archive/'archive_verification.json').read_text())
    source=list(csv.DictReader((archive/'archive_files_22h.csv').open(encoding='utf-8-sig')))
    media=json.loads((root/'media/media_inventory.json').read_text(encoding='utf-8'))
    track=json.loads((archive/'hinnamnor_best_track.json').read_text())['track']
    solar=list(csv.DictReader((archive/'solar_10min.csv').open(encoding='utf-8-sig')))
    # Exclude this research's own derived media from broad-name cache candidates.
    local=json.loads((archive/'local_cache.json').read_text())
    local['matches']=[r for r in local['matches'] if root not in Path(r['path']).resolve().parents]
    local['satellite_objects_cached_by_exact_filename_and_size']=sum(r['cached_size_verified']=='True' for r in source)
    (archive/'local_cache.json').write_text(json.dumps(local,indent=2),encoding='utf-8')
    report['local_cache_matches']=local['matches']
    (archive/'archive_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    dest=root/'plans';dest.mkdir(exist_ok=False)
    def sequence(start,count,step):
        return [(utc_time(start)+timedelta(minutes=step*i)).isoformat() for i in range(count)]
    plans={
        'pilot_three_scans':sequence('2022-08-31T08:30:00Z',3,90),
        'preferred_sunset_30min':sequence('2022-08-31T08:30:00Z',7,30),
        'preferred_sunset_10min':sequence('2022-08-31T08:30:00Z',19,10),
        'backup_sunrise_30min':sequence('2022-08-31T20:00:00Z',7,30)}
    budgets=[];scan_budgets=[]
    for name,times in plans.items():
        selected=[r for r in source if r['nominal_utc'] in times and (r['kind']=='L2' or r['regional']=='True')]
        assert len(selected)==12*len(times) and all(r['status']=='listed' for r in selected)
        write_csv(dest/(name+'_files.csv'),selected)
        hsd=sum(int(r['bytes']) for r in selected if r['kind']=='HSD')
        l2=sum(int(r['bytes']) for r in selected if r['kind']=='L2')
        hsd_counts={band:sum(int(r['bytes']) for r in selected if r['band_or_product']==band) for band in ['B03','B07','B13']}
        total=hsd+l2
        budgets.append({'plan':name,'scans':len(times),'start_utc':times[0],'end_utc':times[-1],
                        'files':len(selected),'regional_hsd_bytes':hsd,'whole_l2_bytes':l2,'total_download_bytes':total,
                        'total_decimal_gb':total/1e9,'total_gib':total/2**30,'cached_bytes':0,
                        'within_5gb_batch_proposal':total<=5_000_000_000,
                        'raw_only_fits_free_minus_10gb':total<=report['disk_free_bytes']-10_000_000_000,
                        'B03_bytes':hsd_counts['B03'],'B07_bytes':hsd_counts['B07'],'B13_bytes':hsd_counts['B13'],
                        'status':'proposal_only_no_download'})
        for stamp in times:
            rows=[r for r in selected if r['nominal_utc']==stamp]
            scan_budgets.append({'plan':name,'nominal_utc':stamp,
                                **{k+'_bytes':sum(int(r['bytes']) for r in rows if r['band_or_product']==k)
                                   for k in ['B03','B07','B13','CMSK','CHGT','CPHS']},
                                'total_bytes':sum(int(r['bytes']) for r in rows)})
    write_csv(dest/'budgets.csv',budgets);write_csv(dest/'per_scan_budgets.csv',scan_budgets)
    # Input/output evidence checks independent of budget construction.
    assert len(source)==133*33
    assert sum(r['status']=='listed' for r in source)==4323
    assert len(report['missing_hsd_scans'])==len(report['missing_l2_scans'])==2
    assert len(media['stills'])==media['unique_still_pixels']==30
    assert media['videos'][0]['full_video_decoded'] and media['videos'][0]['ffmpeg_exit_code']==0
    for record in media['stills']+media['videos']:
        with Path(record['file']).open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest()==record['sha256']
    # Cross-check Earth-fixed vector implementation against the library's direct zenith interface.
    errors=[]
    for row in solar:
        t=utc_time(row['nominal_utc']);lon,lat=interpolate(track,t)
        expected=90-float(astronomy.sun_zenith_angle(t.replace(tzinfo=None),lon,lat))
        errors.append(abs(expected-float(solar_weights(t,lon,lat).elevation_deg)))
    assert max(errors)<1e-4
    # Actual filename endpoints: report center solar at each proposed short-sequence L2 interval.
    endpoint_solar=[]
    for row in source:
        if row['nominal_utc'] not in plans['preferred_sunset_10min'] or row['band_or_product']!='CMSK':continue
        values=[]
        for key in ['filename_start_utc','filename_end_utc']:
            t=utc_time(row[key]);lon,lat=interpolate(track,t)
            values.append(float(solar_weights(t,lon,lat).elevation_deg))
        endpoint_solar.append({'nominal_utc':row['nominal_utc'],'filename_start_utc':row['filename_start_utc'],
                               'filename_end_utc':row['filename_end_utc'],'center_elevation_start_deg':values[0],
                               'center_elevation_end_deg':values[1],'both_center_endpoints_below_minus6':all(v<=-6 for v in values),
                               'note':'L2 filename interval only; per-pixel AHI band timing/eligibility still requires HSD headers'})
    write_csv(dest/'preferred_l2_endpoint_solar.csv',endpoint_solar)
    result={'budgets':budgets,'sun_crossings':report['sun_crossings_interpolated'],
            'solar_direct_zenith_max_difference_deg':max(errors),'reference_source_sha256_rechecked':True,
            'available_objects':4323,'missing_rows':66,'candidate_scans':133,'complete_scans':131,
            'cached_satellite_objects':local['satellite_objects_cached_by_exact_filename_and_size'],
            'satellite_body_downloaded_bytes':0,'ges_sha256_unchanged':report['ges_sha256_unchanged'],
            'raw_and_exports_size_mtime_unchanged':report['protected_size_mtime_unchanged'],
            'protected_files':report['protected_file_count'],
            'limitations':'Availability and timing research only; no AHI radiance, L2 variable schema or exact reference meteorological UTC match inspected. '
                          'Full-file budgets exact compressed object bytes; scratch/decoded memory additional. '
                          'L2 range budget not yet measurable; no Goni chunk-size reuse assumed.'}
    (root/'research_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
