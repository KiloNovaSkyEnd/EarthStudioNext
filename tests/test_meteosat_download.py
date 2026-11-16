from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
import json
import unittest
from datetime import datetime

from ges.meteosat_download import probe_bytes,download_native,native_location
from ges.storage import StorageConfig
from ges.render import observation_interval


ITEM={'native_entry_url':'https://api.eumetsat.int/data/product/entry?name=product.nat',
      'product_id':'product','platform':'MSG4','scan_start_utc':'2020-10-29T16:30:10Z'}


def response(status,headers,body=b'abc'):
    r=Mock(status_code=status,headers=headers)
    r.__enter__=Mock(return_value=r); r.__exit__=Mock(return_value=False)
    r.iter_content.return_value=[body]
    return r


class NativeDownloadTests(unittest.TestCase):
    def test_actual_seviri_scan_is_not_nominal_slot(self):
        nominal=datetime(2020,10,29,16,30)
        actual=datetime(2020,10,29,16,30,10,388000)
        end=datetime(2020,10,29,16,42,43,26000)
        self.assertEqual(observation_interval({'start_time':nominal,'end_time':datetime(2020,10,29,16,45),
            'time_parameters':{'observation_start_time':actual,'observation_end_time':end}}),
            ('2020-10-29T16:30:10.388000Z','2020-10-29T16:42:43.026000Z'))

    def test_exact_range_size_and_access_failure(self):
        token=SimpleNamespace(auth='dummy')
        self.assertEqual(probe_bytes(ITEM,token,Mock(return_value=response(206,{'Content-Range':'bytes 0-0/3'}))),3)
        for r in [response(403,{}),response(200,{'Content-Length':'3'}),response(206,{'Content-Range':'bytes 0-0/*'})]:
            with self.assertRaises((ValueError,RuntimeError)):
                probe_bytes(ITEM,token,Mock(return_value=r))

    def test_atomic_verified_download_and_no_raw_overwrite(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=StorageConfig(root/'raw',root/'processed',root/'exports',reserve_free_gb=0)
            get=Mock(return_value=response(200,{'Content-Length':'3'}))
            path=download_native(ITEM,3,cfg.raw_dir,cfg,SimpleNamespace(auth='dummy'),get)
            meta=json.loads(path.read_text()); data=Path(meta['local_files'][0])
            self.assertEqual(data.read_bytes(),b'abc');self.assertEqual(meta['object_sizes'],[3])
            self.assertTrue(meta['downloaded']);self.assertEqual(len(meta['sha256']),64)
            with self.assertRaises(FileExistsError):
                download_native(ITEM,3,cfg.raw_dir,cfg,SimpleNamespace(auth='dummy'),get)

    def test_incomplete_stream_and_budget_never_publish(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=StorageConfig(root/'raw',root/'processed',root/'exports',reserve_free_gb=0)
            get=Mock(return_value=response(200,{'Content-Length':'4'},b'abc'))
            with self.assertRaises(IOError):
                download_native(ITEM,4,cfg.raw_dir,cfg,SimpleNamespace(auth='dummy'),get)
            self.assertEqual(list(root.rglob('*.nat')),[]);self.assertEqual(list(root.rglob('*.part')),[])
            with self.assertRaises(RuntimeError):
                download_native(ITEM,6_000_000_000,cfg.raw_dir,cfg,SimpleNamespace(auth='dummy'),get)
            self.assertEqual(get.call_count,1)

    def test_native_url_cannot_escape_or_send_auth_to_other_host(self):
        for url in ['https://evil.example/entry?name=product.nat',
                    'https://api.eumetsat.int/entry?name=../product.nat']:
            with self.assertRaises(ValueError):native_location({**ITEM,'native_entry_url':url})
