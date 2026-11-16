"""Revalidation bypasses reprojection, while changed native pages invalidate it."""
import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from http.client import RemoteDisconnected
from ges_next.preview_server import handler,native_signature

class PreviewHttpCacheTests(unittest.TestCase):
    def test_revalidation_and_source_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'scan';folder.mkdir()
            (root/'manifest.json').write_text('{}');(folder/'manifest.json').write_text('{}')
            master=folder/'master.vrt';master.write_text('<VRTDataset><SourceFilename relativeToVRT="1">page.tif</SourceFilename></VRTDataset>')
            page=folder/'page.tif';page.write_bytes(b'original')
            before=native_signature(master)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(root))
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            url=f'http://127.0.0.1:{server.server_port}/data/scan/tiles/0/1/0.png'
            try:
                with patch('ges_next.preview_server._cached_native_tile',return_value=b'png') as render:
                    with urlopen(url) as response:
                        etag=response.headers['ETag'];self.assertEqual(response.read(),b'png')
                        self.assertIn('must-revalidate',response.headers['Cache-Control'])
                    with self.assertRaises(HTTPError) as caught:urlopen(Request(url,headers={'If-None-Match':etag}))
                    self.assertEqual(caught.exception.code,304);self.assertEqual(render.call_count,1)
                    page.write_bytes(b'changed and larger');self.assertNotEqual(before,native_signature(master))
                    with urlopen(Request(url,headers={'If-None-Match':etag})) as response:
                        self.assertEqual(response.status,200);self.assertNotEqual(response.headers['ETag'],etag)
                    self.assertEqual(render.call_count,2)
                    with urlopen(f'http://127.0.0.1:{server.server_port}/data/manifest.json') as response:
                        self.assertEqual(response.headers['Cache-Control'],'no-store')
                    with self.assertRaises(HTTPError) as caught:urlopen(url.replace('/0/1/0.png','/0/2/0.png'))
                    self.assertEqual(caught.exception.code,404)
                    render.side_effect=ConnectionAbortedError('viewport cancelled')
                    with self.assertRaises(RemoteDisconnected):urlopen(url)
                    render.side_effect=ValueError('测试：素材不可读')
                    with self.assertRaises(HTTPError) as caught:urlopen(url)
                    self.assertEqual(caught.exception.code,500)
                    self.assertEqual(caught.exception.reason,'Native tile unavailable')
                    # Prepared previews remain available even if native processing fails.
                    (folder/'preview_4096_test.png').write_bytes(b'prepared-preview')
                    calls=render.call_count
                    with urlopen(url.rsplit('/tiles/',1)[0]+'/preview_4096_test.png') as response:
                        self.assertEqual(response.read(),b'prepared-preview')
                        self.assertEqual(response.headers['Content-Type'],'image/png')
                    self.assertEqual(render.call_count,calls)
            finally:
                server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
