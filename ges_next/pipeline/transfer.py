"""Read verified historical cache in place; new payloads belong only to this scan job."""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock,Event
from pathlib import Path
from ges_next.production.assets import digest,write_json
from ges_next.production.owned_files import owned_path
from ges_next.path_identity import canonical
from .network_retry import retry,DownloadCancelled


def cached(path,item):
    path=Path(path);receipt=Path(str(path)+'.json')
    if not path.is_file() or not receipt.is_file():return False
    try:
        data=json.loads(receipt.read_text(encoding='utf-8'))
        return data['key']==item['key'] and data['bytes']==item['bytes'] and data['etag']==item['etag'] and \
            data['source']=='NOAA anonymous S3 Himawari9' and path.stat().st_size==item['bytes'] and digest(path)==data['sha256']
    except (KeyError,ValueError,OSError):return False


def acquire(step,root,cache_root,client,report,cancelled=None):
    from datetime import datetime
    stamp=datetime.fromisoformat(step['utc'].replace('Z','+00:00')).strftime('%Y%m%dT%H%MZ')
    root=Path(root);paths=[];downloaded=reused=0;report_lock=Lock();abort=Event();primary=[]
    def stopped():return abort.is_set() or (cancelled is not None and cancelled())
    def emit(value):
        with report_lock:report(value)
    def one(index_item):
        try:return transfer(index_item)
        except Exception as error:
            with report_lock:
                if not isinstance(error,DownloadCancelled) and not primary:primary.append(error)
            abort.set();raise
    def transfer(index_item):
        if stopped():raise DownloadCancelled('下载已取消，输入保留')
        index,item=index_item;added=hit=0
        name=Path(item['key']).name;target=root/'raw'/stamp/name
        old=Path(cache_root)/'raw'/stamp/name if cache_root else None
        if old and cached(old,item):path=old;hit=1
        elif cached(target,item):path=target
        else:
            owned_path(root,target,'l1');target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():raise ValueError('本作业输入身份改变，已保留；请建立新候选，不能覆盖')
            part=target.with_name(target.name+'.part');owned_path(root,part,'l1')
            if part.exists() and part.stat().st_nlink!=1:raise ValueError('Shared partial input preserved')
            def download():
                # Recheck ownership on every retry before truncating this job's partial.
                owned_path(root,part,'l1')
                if part.exists() and part.stat().st_nlink!=1:raise ValueError('Shared partial input preserved')
                response=client.get_object(Bucket=item['bucket'],Key=item['key'],IfMatch=item['etag'])
                body=response['Body'];sha=hashlib.sha256();size=0
                try:
                    with part.open('wb') as stream:
                        while chunk:=body.read(1024*1024):
                            if stopped():raise DownloadCancelled('下载已取消，输入保留')
                            size+=len(chunk)
                            if size>item['bytes']:raise ValueError('远端对象大小改变，停止本时次')
                            stream.write(chunk);sha.update(chunk)
                            emit(dict(phase='downloading',utc=step['utc'],completed=index,total=60,object_bytes=size))
                        stream.flush();os.fsync(stream.fileno())
                finally:body.close()
                # Close network resources before committing the final file. A close failure
                # must not cause a retry to replace an already installed input.
                if size!=item['bytes']:raise ValueError('下载未完整，保留临时文件等待重试')
                # Persist identity before installation: a crash cannot leave an unreceipted final file.
                write_json(Path(str(target)+'.json'),dict(key=item['key'],bytes=size,etag=item['etag'],sha256=sha.hexdigest(),source='NOAA anonymous S3 Himawari9'))
                part.replace(target)
                return size
            def retry_report(value):
                value=dict(value,utc=step['utc'],key=item['key'])
                with report_lock:
                    write_json(root/'download_retry.json',value)
                    report(value)
            size=retry(download,retry_report,cancelled=stopped)
            path=target;added=size
        return str(canonical(path)),added,hit
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for index,(path,added,hit) in enumerate(pool.map(one,enumerate(step['objects']))):
                paths.append(path);downloaded+=added;reused+=hit
                emit(dict(phase='inputs-ready',utc=step['utc'],completed=index+1,total=60,reused_files=reused,downloaded_bytes=downloaded))
    except Exception:
        if primary:raise primary[0]
        raise
    write_json(root/'input_selection.json',paths)
    return paths
