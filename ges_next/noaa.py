"""Read-only NOAA L1 object listing. Never downloads satellite payloads."""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
import re
from .selection import utc

AHI_BANDS=('B01','B02','B03','B04','B07','B13')
ABI_BANDS=('C01','C02','C03','C07','C13')


def probe(client,candidate,when):
    when=utc(when)
    if candidate.instrument not in ('ahi','abi'):
        raise NotImplementedError('EUMETSAT FCI/SEVIRI adapter audit pending; no silent legacy substitution')
    bucket='noaa-'+candidate.satellite
    grouped=defaultdict(dict)
    if candidate.instrument=='ahi':
        base=when.replace(minute=when.minute//10*10,second=0,microsecond=0)
        prefixes=[(base+timedelta(minutes=i)).strftime('AHI-L1b-FLDK/%Y/%m/%d/%H%M/') for i in [-10,0,10]]
        pattern=re.compile(r'HS_H\d+_(\d{8})_(\d{4})_(B\d{2})_FLDK_.*_S(\d{2})10\.DAT\.bz2$')
        required=AHI_BANDS
    else:
        base=when.replace(minute=0,second=0,microsecond=0)
        prefixes=[(base+timedelta(hours=i)).strftime('ABI-L1b-RadF/%Y/%j/%H/') for i in [-1,0,1]]
        pattern=re.compile(r'_M\d(C\d{2})_G\d+_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})(\d*)_')
        required=ABI_BANDS
    for prefix in prefixes:
        for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix=prefix):
            for obj in page.get('Contents',[]):
                key=obj['Key'];match=pattern.search(key.split('/')[-1])
                if not match:continue
                if candidate.instrument=='ahi':
                    date,time,band,segment=match.groups()
                    actual=datetime.strptime(date+time,'%Y%m%d%H%M').replace(tzinfo=timezone.utc)
                else:
                    band,year,day,hour,minute,second,fraction=match.groups()
                    actual=datetime(int(year),1,1,tzinfo=timezone.utc)+timedelta(days=int(day)-1,hours=int(hour),minutes=int(minute),seconds=int(second),microseconds=int((fraction+'000000')[:6]))
                    segment='01'
                if band not in required or abs((actual-when).total_seconds())>600:continue
                grouped[actual][(band,segment)]=obj
    complete=[]
    for actual,items in grouped.items():
        expected={(band,f'{i:02}') for band in required for i in (range(1,11) if candidate.instrument=='ahi' else [1])}
        if not expected.issubset(items):continue
        objects=[items[k] for k in sorted(expected)]
        if any(int(o['Size'])<=0 for o in objects):continue
        complete.append(dict(satellite=candidate.satellite,observed_utc=actual.isoformat(),complete=True,
            keys=[o['Key'] for o in objects],sizes=[o['Size'] for o in objects],etags=[o.get('ETag') for o in objects],
            total_bytes=sum(o['Size'] for o in objects),bucket=bucket,product='AHI-L1b-FLDK' if candidate.instrument=='ahi' else 'ABI-L1b-RadF',bands=list(required),payload_downloaded=False))
    if not complete:raise FileNotFoundError('No complete required native L1 scan')
    return min(complete,key=lambda row:abs((utc(row['observed_utc'])-when).total_seconds()))
