"""Line-delimited JSON bridge for the native client. Secrets only arrive on stdin.

Inventory queries do not download satellite imagery or manufacture coverage.
"""
from datetime import timedelta
from pathlib import Path
import json
import sys
from .catalog import utc_time


def emit(kind, **values):
    print(json.dumps({'type': kind, **values}, ensure_ascii=False), flush=True)


def project_times(project):
    start, end = utc_time(project['StartUtc']), utc_time(project['EndUtc'])
    interval = project['IntervalMinutes']
    mode = project.get('CaptureMode', 'sequence')
    if mode not in ('single', 'sequence') or (mode == 'single' and start != end):
        raise ValueError('Single-frame projects require one exact UTC time')
    if interval not in (10, 15, 30, 60) or (mode == 'sequence' and start >= end):
        raise ValueError('Invalid project interval')
    if start.year < 2018 or (end - start).total_seconds() / (interval * 60) > 10000:
        raise ValueError('Project interval out of supported bounds')
    times = []
    while start <= end:
        times.append(start)
        start += timedelta(minutes=interval)
    return times


def candidates(when):
    """Candidates are searched, never claimed operational without real objects.

    Try both possible generations around transitions; no fabricated handover date.
    SEVIRI coverage after MTG transition can be missing and is reported as such.
    """
    east = ['goes16'] if when.year < 2025 else ['goes19', 'goes16']
    west = ['goes17'] if when.year < 2022 else ['goes18', 'goes17']
    return [('亚太 / 日葵', ['himawari8' if when < utc_time('2022-12-13T00:00:00Z') else 'himawari9']),
            ('美洲 / GOES-East', east), ('太平洋 / GOES-West', west),
            ('欧洲非洲 / Meteosat', ['zero']), ('印度洋 / Meteosat', ['iodc'])]


def query(when, choices, client):
    from .catalog import himawari_scene, goes_scene, scene_as_json
    from .meteosat import search_observation
    errors = []
    for source in choices:
        try:
            if source in ('zero', 'iodc'):
                record = search_observation(when, source, 10)
                return {'source': source, 'observed': record['scan_start_utc'],
                        'bytes': None, 'native': record, 'quality': 'SEVIRI目录；字节数与波段须下载前核验'}
            scene = (himawari_scene(client, when, ('B01', 'B02', 'B03', 'B07', 'B13'), 10)
                     if source.startswith('himawari') else goes_scene(client, when, source, 10))
            return {'source': source, 'observed': scene.observed_utc.isoformat(),
                    'bytes': scene.total_bytes, 'native': scene_as_json(scene),
                    'quality': 'AHI原生波段目录' if source.startswith('himawari') else
                    'ABI MCMIP产品目录（2km）；高分辨率L1b适配尚未接入'}
        except FileNotFoundError:
            errors.append('missing')
        except Exception:
            # Do not expose HTTP credentials, redirects or request bodies.
            errors.append('unavailable')
    return {'source': '/'.join(choices), 'state': 'missing' if all(e == 'missing' for e in errors) else 'unavailable'}


def scan(project, out, query_fn=None, client=None, groups_fn=None, checkpoint_every=1, publish_fn=None):
    if type(checkpoint_every) is not int or not 1<=checkpoint_every<=100:raise ValueError("Invalid catalog checkpoint interval")
    times = project_times(project)
    groups_fn=groups_fn or candidates
    plan=[(when,groups_fn(when)) for when in times]
    if query_fn is None:
        query_fn = query
    if client is None:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        client = boto3.client('s3', region_name='us-east-1', config=Config(signature_version=UNSIGNED,
            connect_timeout=5, read_timeout=20, retries={'max_attempts': 1}))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    records, seen = [], set()
    total = sum(len(groups) for _,groups in plan)
    if not total: raise ValueError('搜索前请至少选择一颗卫星。')
    published=0
    def checkpoint():
        body = {'kind': 'catalog-only; no downloaded imagery or coverage proof',
                'project_id': project['Id'], 'records': records, 'expected_records': total,
                'project_spec':project,
                'satellite_selection':project.get('SatelliteSelection',{'Mode':'auto','Satellites':[]}),
                'finished': len(records) == total,
                'known_unique_bytes': sum(r['additional_known_bytes'] for r in records),
                'unknown_sizes': sum(r.get('state') == 'available' and r.get('bytes') is None for r in records)}
        if publish_fn is not None:publish_fn(out/'inventory.json',body)
        else:
            temporary = out / 'inventory.tmp'
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(out / 'inventory.json')
    try:
        for when,groups in plan:
            for region, sources in groups:
                emit('status', message=f'正在检查 {when:%Y-%m-%d %H:%M} UTC · {region}')
                record = query_fn(when, sources, client)
                record.update(region=region, requested_utc=when.isoformat())
                record.setdefault('state', 'available')
                identity = json.dumps(record.get('native', {}).get('keys', record.get('native', {}).get('product_id', '')))
                unique_bytes = 0
                if record.get('bytes') is not None and identity not in seen:
                    unique_bytes = record['bytes']
                    seen.add(identity)
                record['additional_known_bytes'] = unique_bytes
                records.append(record)
                if len(records)==1 or len(records)==total or len(records)%checkpoint_every==0:
                    checkpoint();published=len(records)
                emit('progress', completed=len(records), total=total, record=record)
    finally:
        if records and published!=len(records):checkpoint()
    return str(out / 'inventory.json')


def main():
    request = json.load(sys.stdin)
    action = request['action']
    try:
        if action == 'account-status':
            from .eumetsat_auth import credential_path
            configured = credential_path().is_file()
            emit('result', configured=configured, message='本机凭据存在；未验证许可与下载权限' if configured else '尚未连接 EUMETSAT 账户')
        elif action == 'connect-account':
            from .eumetsat_auth import authenticated_token, save_credentials
            key, secret = request['options']['key'], request['options']['secret']
            authenticated_token((key, secret))
            save_credentials(key, secret)
            emit('result', configured=True, message='认证通过，凭据已由 Windows 当前用户加密保存；具体产品许可需查询核验')
        elif action == 'scan':
            path = scan(request['project'], request['options']['output'])
            emit('result', path=path, message='目录检查结束；未下载卫星文件，也未生成天气动画')
        else:
            raise ValueError('Unsupported action')
    except Exception as error:
        if action == 'connect-account':
            message = '连接失败，请检查API密钥、网络与账户许可。输入未保存。'
        elif isinstance(error, ValueError):
            message = str(error)
        else:
            message = '任务失败，请检查网络和目录权限；已完成的目录记录保留。'
        emit('error', message=message)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
