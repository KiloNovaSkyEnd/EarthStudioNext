"""Anonymous, read-only inventory of real historical SEVIRI observations.

Download/reader integration is deliberately not claimed by this inventory.
Catalog size fields have no explicit byte unit and must not bypass budgets.
"""
from datetime import datetime, timedelta
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from .catalog import utc_time

COLLECTIONS = {'zero':'EO:EUM:DAT:MSG:HRSEVIRI',
               'iodc':'EO:EUM:DAT:MSG:HRSEVIRI-IODC'}
SEARCH_URL = 'https://api.eumetsat.int/data/search-products/1.0.0/os'


def _iso(when):
    return when.isoformat().replace('+00:00','Z')


def select_observation(response: dict, when: datetime, service: str, minutes=20) -> dict:
    """Prefer an actual scan interval containing UTC; filename dates are not starts."""
    if service not in COLLECTIONS or not isinstance(minutes,int) or not 0 <= minutes <= 60:
        raise ValueError('Known SEVIRI service and 0..60 minute window required')
    when = utc_time(when.isoformat())  # also rejects naive timestamps.
    features = response['features']
    if response.get('totalResults',len(features)) > len(features):
        raise ValueError('Truncated inventory; refusing to select from an incomplete result')
    selected=[]
    for feature in features:
        props=feature['properties']
        if props.get('parentIdentifier') != COLLECTIONS[service]:
            continue
        acquisition=props['acquisitionInformation'][0]
        if acquisition['instrument']['instrumentShortName'] != 'SEVIRI':
            continue
        start_text,end_text=props['date'].split('/')
        start,end=utc_time(start_text),utc_time(end_text)
        if end < start:
            raise ValueError('SEVIRI scan interval is reversed')
        distance=max((start-when).total_seconds(),(when-end).total_seconds(),0)
        if distance > minutes*60:
            continue
        links=props['links']
        native=next((entry for entry in links.get('sip-entries',[])
                     if entry.get('title','').endswith('.nat')),None)
        download=links['data'][0]
        for entry in [native,download]:
            if entry and (urlsplit(entry['href']).scheme != 'https'
                          or urlsplit(entry['href']).hostname != 'api.eumetsat.int'):
                raise ValueError('Unexpected product download host')
        record={
            'kind':'catalog inventory only; NOT downloaded or rendered observations',
            'service':service,'collection':COLLECTIONS[service],
            'product_id':props['identifier'],
            'platform':acquisition['platform']['platformShortName'],
            'instrument':'SEVIRI','scan_start_utc':_iso(start),'scan_end_utc':_iso(end),
            'reference_utc':_iso(when),'scan_contains_reference':start <= when <= end,
            'start_offset_seconds':(start-when).total_seconds(),
            'end_offset_seconds':(end-when).total_seconds(),
            'distance_to_scan_interval_seconds':distance,
            'catalog_size_value':props['productInformation'].get('size'),
            'catalog_size_unit':'unspecified; NOT verified download bytes',
            'download_url':download['href'],
            'native_entry_url':native['href'] if native else None,
            'downloaded':False,'render_verified':False,
            'notes':'Scan timing is not simultaneous per-pixel UTC. Footprint and '
                    'IR band calibration require real-file validation. No pixels added.',
        }
        selected.append((distance,abs(((start+(end-start)/2)-when).total_seconds()),record))
    if not selected:
        raise FileNotFoundError('No actual SEVIRI scan in the requested UTC window')
    return min(selected,key=lambda item:item[:2])[2]


def search_observation(when: datetime, service: str, minutes=20) -> dict:
    if service not in COLLECTIONS or not isinstance(minutes,int) or not 0 <= minutes <= 60:
        raise ValueError('Known SEVIRI service and 0..60 minute window required')
    when=utc_time(when.isoformat())
    # Include the preceding 15-minute full-disk scan, even for minutes=0.
    params={'format':'json','pi':COLLECTIONS[service],
            'dtstart':_iso(when-timedelta(minutes=minutes+15)),
            'dtend':_iso(when+timedelta(minutes=minutes+15)),'c':100}
    url=SEARCH_URL+'?'+urlencode(params)
    with urlopen(url,timeout=30) as response:
        data=json.load(response)
    result=select_observation(data,when,service,minutes)
    result['catalog_query_url']=url
    return result
