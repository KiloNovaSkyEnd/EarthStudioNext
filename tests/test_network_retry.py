import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from botocore.exceptions import EndpointConnectionError, ClientError, ResponseStreamingError
from ges_next.pipeline.network_retry import retry, transient,DownloadCancelled
from ges_next.pipeline.transfer import acquire, cached


class NetworkRetryTests(unittest.TestCase):
    def test_dns_recovers_with_bounded_backoff(self):
        calls=[];reports=[];delays=[]
        def operation():
            calls.append(1)
            if len(calls)<3:raise EndpointConnectionError(endpoint_url='https://fixture.invalid')
            return 'ok'
        self.assertEqual(retry(operation,reports.append,sleep=delays.append),'ok')
        self.assertEqual(delays,[5,10]);self.assertEqual(len(reports),3)
        self.assertEqual(reports[-1]['phase'],'download-recovered')

    def test_unattended_survives_more_than_twelve_failures(self):
        calls=[];delays=[]
        def operation():
            calls.append(1)
            if len(calls)<=20:raise EndpointConnectionError(endpoint_url='https://fixture.invalid')
            return 'recovered'
        self.assertEqual(retry(operation,lambda _:None,sleep=delays.append),'recovered')
        self.assertEqual(len(calls),21);self.assertEqual(max(delays),60)

    def test_user_pause_interrupts_wait_without_another_request(self):
        calls=[];stop=[]
        def operation():calls.append(1);raise EndpointConnectionError(endpoint_url='https://fixture.invalid')
        with self.assertRaises(DownloadCancelled):
            retry(operation,lambda _:None,sleep=lambda _:stop.append(True),cancelled=lambda:bool(stop))
        self.assertEqual(len(calls),1)

    def test_exhaustion_preserves_error(self):
        error=EndpointConnectionError(endpoint_url='https://fixture.invalid');delays=[]
        def operation():raise error
        with self.assertRaises(EndpointConnectionError) as caught:
            retry(operation,lambda v:None,attempts=4,sleep=delays.append)
        self.assertIs(caught.exception,error);self.assertEqual(delays,[5,10,20])

    def test_identity_permission_and_missing_errors_not_retried(self):
        for error in [ValueError('wrong size'),OSError('disk full')]+[
            ClientError({'Error':{'Code':str(status)},'ResponseMetadata':{'HTTPStatusCode':status}},'GetObject')
            for status in [403,404,412]]:
            self.assertFalse(transient(error));calls=[]
            def operation():calls.append(1);raise error
            with self.assertRaises(type(error)):retry(operation,lambda v:None,sleep=lambda _:self.fail('unexpected delay'))
            self.assertEqual(len(calls),1)
        self.assertTrue(transient(ClientError({'Error':{'Code':'SlowDown'},'ResponseMetadata':{'HTTPStatusCode':503}},'GetObject')))

    def test_stream_interruption_restarts_partial_and_reuses_receipt(self):
        class Broken(io.BytesIO):
            def read(self,n=-1):
                if self.tell():raise ResponseStreamingError(error='connection lost')
                return super().read(2)
        bodies=[];calls=[]
        class Client:
            def get_object(self,**kwargs):
                calls.append(kwargs);body=Broken(b'abcd') if len(calls)==1 else io.BytesIO(b'abcd')
                bodies.append(body);return dict(Body=body)
        item=dict(bucket='fixture',key='test.DAT.bz2',etag='frozen-etag',bytes=4)
        step=dict(utc='2026-10-14T01:00:00Z',objects=[item]);reports=[]
        parent=Path(__file__).resolve().parents[1]/'reports'
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            root=Path(tmp)
            with patch('ges_next.pipeline.transfer.retry',side_effect=lambda op,report,**kw:retry(op,report,sleep=lambda _:None,**kw)):
                paths=acquire(step,root,None,Client(),reports.append)
            target=Path(paths[0]);self.assertEqual(target.read_bytes(),b'abcd');self.assertTrue(cached(target,item))
            self.assertEqual(len(calls),2);self.assertTrue(all(b.closed for b in bodies))
            self.assertTrue(all(c['IfMatch']=='frozen-etag' for c in calls))
            self.assertTrue((root/'download_retry.json').exists())
            acquire(step,root,None,Client(),reports.append)
            self.assertEqual(len(calls),2)

    def test_permanent_sibling_failure_cancels_offline_retry(self):
        import threading,time
        offline=threading.Event()
        class Client:
            def get_object(self,**kw):
                if kw['Key']=='offline':
                    offline.set();raise EndpointConnectionError(endpoint_url='https://fixture.invalid')
                offline.wait(2)
                raise ClientError({'Error':{'Code':'AccessDenied'},'ResponseMetadata':{'HTTPStatusCode':403}},'GetObject')
        step=dict(utc='2026-10-14T01:00:00Z',objects=[dict(bucket='fixture',key=k,etag='same',bytes=4) for k in ['offline','denied']])
        parent=Path(__file__).resolve().parents[1]/'reports'
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            start=time.monotonic()
            with self.assertRaises(ClientError):acquire(step,Path(tmp),None,Client(),lambda _:None)
            self.assertLess(time.monotonic()-start,3)
            self.assertFalse((Path(tmp)/'input_selection.json').exists())

    def test_power_request_restored_after_error(self):
        from ges_next.pipeline.power import keep_awake
        calls=[]
        def setter(value):calls.append(value);return 0x80000000
        with self.assertRaises(ValueError):
            with keep_awake(setter=setter):raise ValueError('fixture')
        self.assertEqual(calls,[0x80000001,0x80000000])


if __name__=='__main__':unittest.main()
