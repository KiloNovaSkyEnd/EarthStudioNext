import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import h5py
import numpy as np
import ges.range_archive as archive_module
from ges.range_archive import RangeArchive
from ges.storage import StorageConfig
from ges.goni_data import decode


class FakeS3:
    def __init__(self,data):self.data=data;self.calls=[]
    def get_object(self,**kw):
        start,end=map(int,kw['Range'].removeprefix('bytes=').split('-'));self.calls.append((start,end))
        return {'ContentRange':f'bytes {start}-{end}/{len(self.data)}','Body':io.BytesIO(self.data[start:end+1])}


class RangeArchiveTests(unittest.TestCase):
    def test_three_dimensional_quality_flag_slice_prefetches_exact_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'flag.h5';original=np.arange(20*30,dtype=np.int16).reshape(20,30,1)
            with h5py.File(file,'w') as f:f.create_dataset('flag',data=original,chunks=(5,5,1),compression='gzip')
            body=file.read_bytes();cfg=StorageConfig(root/'raw',root/'processed',root/'exports',reserve_free_gb=0)
            with RangeArchive(FakeS3(body),'test','flag',len(body),'etag',root/'raw/ranges',cfg,max_bytes=100000,block_size=1024) as stream:
                with h5py.File(stream,'r') as f:
                    actual=decode(f['flag'],np.s_[3:13,7:19,0],stream)
            np.testing.assert_array_equal(actual,original[3:13,7:19,0])

    def test_real_hdf5_subset_is_byte_exact_and_reuses_verified_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'fixture.h5';original=np.arange(80*90,dtype=np.float32).reshape(80,90)
            with h5py.File(file,'w') as f:
                f.create_dataset('height',data=original,chunks=(10,10),compression='gzip')
            body=file.read_bytes();s3=FakeS3(body);cfg=StorageConfig(root/'raw',root/'processed',root/'exports',reserve_free_gb=0)
            def read():
                with RangeArchive(s3,'test','fixture',len(body),'etag',root/'raw/ranges',cfg,max_bytes=100000,block_size=1024) as stream:
                    with h5py.File(stream,'r') as f:
                        stream.prefetch_variable(f['height'],np.s_[13:38,22:55])
                        values=f['height'][13:38,22:55]
                return values
            np.testing.assert_array_equal(read(),original[13:38,22:55]);calls=len(s3.calls)
            np.testing.assert_array_equal(read(),original[13:38,22:55]);self.assertEqual(len(s3.calls),calls)
            block=next((root/'raw/ranges').glob('*.bin'));block.write_bytes(b'corrupted')
            with self.assertRaises(IOError):read()

    def test_aggregate_cap_stops_before_network_fetch(self):
        old=archive_module._GROUP
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);cfg=StorageConfig(root/'raw',root/'processed',root/'exports',reserve_free_gb=0)
                counter=SimpleNamespace(value=0);archive_module.configure_group_budget(counter,threading.Lock(),1024)
                s3=FakeS3(bytes(range(256))*16)
                with RangeArchive(s3,'test','bytes',4096,'etag',root/'raw/ranges',cfg,max_bytes=4096,block_size=1024) as stream:
                    self.assertEqual(len(stream.read(100)),100)
                    stream.seek(1024)
                    with self.assertRaises(RuntimeError):stream.read(10)
                self.assertEqual(len(s3.calls),1);self.assertEqual(counter.value,1024)
        finally:archive_module._GROUP=old

    def test_declared_fill_range_and_scale_are_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            with h5py.File(Path(directory)/'fields.h5','w') as f:
                d=f.create_dataset('height',data=np.array([1,-99,12],np.int16));d.attrs['_FillValue']=-99
                d.attrs['valid_range']=[0,10];d.attrs['scale_factor']=2.;d.attrs['add_offset']=1.
                value=decode(d,np.s_[:]);self.assertEqual(value[0],3.);self.assertTrue(np.isnan(value[1:]).all())
