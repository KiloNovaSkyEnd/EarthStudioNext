"""One bounded real sunrise sample, four AHI bands/one segment, never full disk."""
import hashlib
import json
import os
from pathlib import Path

from ges.catalog import s3_client
from ges.storage import load_config, preflight


def main():
    cfg = load_config()
    raw = cfg.raw_dir/'ahi_twilight_dawn_20220831T2200Z'
    raw.mkdir(exist_ok=False)
    client = s3_client()
    prefix = 'AHI-L1b-FLDK/2022/08/31/2200/'
    listing = client.list_objects_v2(Bucket='noaa-himawari8', Prefix=prefix)
    selected = [dict(key=x['Key'], bytes=x['Size'], etag=x['ETag']) for x in listing.get('Contents', [])
                if any(f'_B{b:02}_' in x['Key'] for b in [1, 2, 3, 4]) and '_S0310' in x['Key']]
    assert len(selected) == 4
    total = sum(x['bytes'] for x in selected)
    hard_limit = 100_000_000
    assert 0 < total < hard_limit
    plan = dict(bucket='noaa-himawari8', nominal_utc='2022-08-31T22:00:00Z',
                files=selected, listed_bytes=total, hard_limit_bytes=hard_limit,
                disk_preflight=preflight(total, raw, cfg),
                scope='Four measured visible/NIR bands, only segment03; source RGB sunrise validation, not new full3D weather')
    (raw/'download_plan.json').write_text(json.dumps(plan, indent=2))
    count = 0
    hashes = {}
    for item in selected:
        response = client.get_object(Bucket=plan['bucket'], Key=item['key'], IfMatch=item['etag'])
        assert response['ContentLength'] == item['bytes'] and response['ETag'] == item['etag']
        target = raw/Path(item['key']).name
        partial = target.with_suffix(target.suffix+'.part')
        digest = hashlib.sha256()
        actual = 0
        try:
            with partial.open('xb') as stream:
                for chunk in response['Body'].iter_chunks(chunk_size=1024*1024):
                    actual += len(chunk)
                    count += len(chunk)
                    if actual > item['bytes'] or count > hard_limit:
                        raise ValueError('Download exceeded declared size/budget; partial retained')
                    stream.write(chunk)
                    digest.update(chunk)
        finally:
            response['Body'].close()
        assert actual == item['bytes']
        os.replace(partial, target)
        hashes[str(target.resolve())] = digest.hexdigest()
        print('VERIFIED', target.name, actual, flush=True)
    assert count == total
    (raw/'download_verification.json').write_text(json.dumps({**plan, 'actual_bytes': count, 'sha256': hashes}, indent=2))
    # A declared subarea of the earlier1km area, exactly within acquired S03.
    previous = json.loads((cfg.processed_dir/'hinnamnor_geocolor_v1/0830/official_metadata.json').read_text())
    meta = {**previous, 'nominal_utc': plan['nominal_utc'], 'native_crop_yx': [1100, 1650, 1500, 3000],
            'output_shape_yx': [1100, 3000], 'area_extent_m': [-2499999.95507942, 2199999.96046989, 499999.991015885, 3299999.9407048346],
            'input_file_sha256': hashes, 'bands': {}, 'official_config_unmodified': False,
            'scope': 'Real sunrise RGB only, no coincident new IR/cloud classification acquired'}
    (raw/'source_metadata.json').write_text(json.dumps(meta, indent=2))
    print('COMPLETE', count, flush=True)


if __name__ == '__main__':
    main()
