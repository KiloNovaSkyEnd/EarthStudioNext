"""Budgeted, resumable, checksum-recorded downloads; never replace committed raw."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import threading
import requests
from ges.catalog import s3_client
from ges.eumetsat_auth import authenticated_token
from ges.meteosat_download import native_location
from .project import initialize, save, check_disk


def target_for(root, record):
    name = Path(record['key']).name if record['provider'] == 's3' else record['filename']
    return Path(root) / 'raw' / record['sensor'] / record['scene_id'] / name


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(root, row, client, token):
    target = target_for(root, row)
    receipt = target.with_suffix(target.suffix + '.receipt.json')
    if target.exists():
        if target.stat().st_size != row['size']:
            raise RuntimeError(f'Committed raw size mismatch; preserved for inspection: {target.name}')
        if receipt.is_file():
            old = json.loads(receipt.read_text(encoding='utf-8'))
            if old['size'] != row['size'] or old.get('etag') != row.get('etag'):
                raise ValueError('Raw receipt differs from current inventory')
            return {'file': str(target), **old, 'reused': True}
        save(receipt, {'size': row['size'], 'sha256': sha(target), 'etag': row.get('etag')})
        return {'file': str(target), 'size': row['size'], 'reused': True}
    check_disk(root, row['size'])
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + '.part')
    origin_path = part.with_suffix(part.suffix + '.origin.json')
    origin = {'size': row['size'], 'etag': row.get('etag'),
              'identity': row.get('key', row.get('filename'))}
    if part.exists():
        if not origin_path.is_file() or json.loads(origin_path.read_text(encoding='utf-8')) != origin:
            raise ValueError('Partial origin changed or unknown; partial preserved')
    else:
        save(origin_path, origin)
    count = part.stat().st_size if part.exists() else 0
    if count > row['size']:
        raise ValueError('Oversize partial preserved; manual inspection required')
    if count < row['size']:
        if row['provider'] == 's3':
            response = client.get_object(Bucket=row['bucket'], Key=row['key'],
                IfMatch=row['etag'], Range=f'bytes={count}-')
            if response['ContentLength'] != row['size']-count:
                response['Body'].close()
                raise ValueError('S3 range length mismatch')
            try:
                with part.open('ab') as stream:
                    for block in response['Body'].iter_chunks(chunk_size=1024*1024):
                        count += len(block)
                        if count > row['size']:
                            raise ValueError('S3 exceeds inventory size')
                        stream.write(block)
            finally:
                response['Body'].close()
        else:
            url, _ = native_location(row['candidate'])
            with requests.get(url, auth=token.auth, headers={'Range': f'bytes={count}-',
                'Accept-Encoding': 'identity'}, stream=True, timeout=(30, 120)) as response:
                if response.status_code != 206:
                    raise RuntimeError(f'EUMETSAT range HTTP {response.status_code}; partial preserved')
                expected = f'bytes {count}-{row["size"]-1}/{row["size"]}'
                if response.headers.get('Content-Range') != expected:
                    raise ValueError('EUMETSAT content range mismatch')
                with part.open('ab') as stream:
                    for block in response.iter_content(1024*1024):
                        count += len(block)
                        if count > row['size']:
                            raise ValueError('Native stream exceeds verified size')
                        stream.write(block)
    if count != row['size']:
        raise IOError('Incomplete download; partial preserved')
    digest = sha(part)
    part.replace(target)
    value = {'size': count, 'sha256': digest, 'etag': row.get('etag')}
    save(receipt, value)
    return {'file': str(target), **value, 'reused': False}


def download(root, workers=6, limit=None):
    root = Path(root)
    initialize(root)
    plan = json.loads((root / 'inventory.json').read_text(encoding='utf-8'))
    rows = plan['records']
    if limit:
        # A complete first-time sample from all five views, not N arbitrary files.
        selected = {s['scene_id'] for s in plan['scenes'] if s['nominal_utc'] == plan['frames'][0]}
        rows = [r for r in rows if r['scene_id'] in selected]
    remaining = sum(r['size'] for r in rows if not target_for(root, r).exists())
    check_disk(root, remaining)
    client, token = s3_client(), authenticated_token()
    done, errors = [], []
    started = time.time()
    def retry(row):
        for attempt in range(4):
            try:
                return fetch(root, row, client, token)
            except Exception as error:
                if attempt == 3:
                    # Avoid printing response URLs, bodies or credentials.
                    return {'error': type(error).__name__ + ': ' + str(error).split('?')[0][:150],
                            'scene_id': row['scene_id'], 'name': target_for(root, row).name}
                time.sleep(2*(attempt+1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(retry, row) for row in rows]
        for future in as_completed(futures):
            result = future.result()
            (errors if 'error' in result else done).append(result)
            if (len(done)+len(errors)) % 20 == 0 or 'error' in result:
                print('ARCHIVE', len(done), '/', len(rows), 'files;',
                    round(sum(r['size'] for r in done)/1e9, 3), 'GB;', len(errors), 'errors', flush=True)
                save(root / 'reports' / 'download_progress.json', {'completed': len(done), 'total': len(rows),
                     'bytes': sum(r['size'] for r in done), 'errors': errors, 'elapsed_seconds': time.time()-started})
    summary = {'completed': len(done), 'total': len(rows), 'bytes': sum(r['size'] for r in done),
               'errors': errors, 'elapsed_seconds': time.time()-started, 'pilot_only': bool(limit)}
    save(root / 'reports' / ('pilot_download.json' if limit else 'download_verification.json'), summary)
    print('ARCHIVE RESULT', json.dumps(summary), flush=True)
    if errors:
        raise RuntimeError('Some archive objects failed; see sanitized report. Re-run resumes.')
    return summary
