"""Unattended transport recovery; permanent errors and user stops are never hidden."""
import time
from datetime import datetime, timezone
from botocore.exceptions import (ClientError, EndpointConnectionError,
    ConnectionClosedError, ReadTimeoutError, ConnectTimeoutError,
    ResponseStreamingError, IncompleteReadError)

class DownloadCancelled(Exception):
    """The queue/user requested a stop while a download was waiting."""


def wait(delay, sleep, cancelled):
    if cancelled is None:
        sleep(delay);return
    remaining=delay
    while remaining>0:
        if cancelled():raise DownloadCancelled('下载等待已取消，输入保留')
        interval=min(.5,remaining);sleep(interval);remaining-=interval


def transient(error):
    if isinstance(error, (EndpointConnectionError, ConnectionClosedError,
            ReadTimeoutError, ConnectTimeoutError, ResponseStreamingError, IncompleteReadError)):
        return True
    if isinstance(error, ClientError):
        response=error.response
        return (response.get('ResponseMetadata',{}).get('HTTPStatusCode') in (408,429,500,502,503,504)
            or response.get('Error',{}).get('Code') in ('SlowDown','RequestTimeout','InternalError','ServiceUnavailable'))
    return False


def retry(operation, report, *, attempts=None, sleep=time.sleep, cancelled=None):
    attempt=0
    while True:
        if cancelled is not None and cancelled():raise DownloadCancelled('下载等待已取消，输入保留')
        attempt+=1
        try:
            result=operation()
        except Exception as error:
            if not transient(error) or (attempts is not None and attempt>=attempts):raise
            delay=min(60,5*2**min(attempt-1,4))
            report(dict(phase='download-retrying',attempt=attempt,max_attempts=attempts,
                retry_seconds=delay,error_type=type(error).__name__,error=str(error),
                occurred_utc=datetime.now(timezone.utc).isoformat()))
            wait(delay,sleep,cancelled)
        else:
            if attempt>1:report(dict(phase='download-recovered',attempt=attempt,occurred_utc=datetime.now(timezone.utc).isoformat()))
            return result
