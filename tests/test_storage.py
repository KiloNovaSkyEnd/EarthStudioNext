from pathlib import Path
import tempfile
import unittest
from collections import namedtuple
from ges.storage import StorageConfig, load_config, save_config, preflight
from ges.download import download_scene, cached_bytes, read_manifest
from ges.catalog import Scene, utc_time, himawari_scene

Disk = namedtuple('Disk','total used free')

class MockPager:
    def __init__(self, objects): self.objects = objects
    def paginate(self, **kwargs):
        yield {'Contents':[o for o in self.objects if o['Key'].startswith(kwargs['Prefix'])]}
class MockS3:
    def __init__(self, objects=(), payload=b'abcd'):
        self.objects=objects; self.payload=payload; self.calls=0
    def get_paginator(self, what): return MockPager(self.objects)
    def download_file(self, bucket, key, dest):
        self.calls+=1
        Path(dest).write_bytes(self.payload)

class StorageTests(unittest.TestCase):
    def test_config_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            cfg=StorageConfig(tmp/'raw',tmp/'processed',tmp/'export',3.5,0)
            path=tmp/'config.json'
            save_config(cfg,path)
            got=load_config(path)
            self.assertEqual(got.raw_dir,cfg.raw_dir)
            self.assertEqual(got.max_single_scene_gb,3.5)

    def test_nested_directories_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            with self.assertRaises(ValueError):
                StorageConfig(tmp/'raw',tmp/'raw'/'child',tmp/'out').validate()

    def test_disk_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            cfg=StorageConfig(tmp/'raw',tmp/'processed',tmp/'export',1.0,0.01)
            fake=lambda _: Disk(10**9,10**9-15_000_000,15_000_000)
            with self.assertRaises(RuntimeError):
                preflight(20_000_000,tmp/'raw',cfg,disk_usage=fake)
            ok=preflight(20_000_000,tmp/'raw',cfg,existing_bytes=16_000_000,disk_usage=fake)
            self.assertEqual(ok['remaining_gb'],0.004)

    def test_download_reuse_redownload_corrupt_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            cfg=StorageConfig(root/'raw',root/'processed',root/'export',1,0)
            scene=Scene('goes16','noaa-goes16','pfx',utc_time('2020-10-29T16:40:00Z'),
                        ('pfx/file.nc',),4,'ABI-L2-MCMIPF',(4,))
            s3=MockS3(payload=b'abcd')
            manifest=download_scene(s3,scene,cfg.raw_dir,cfg)
            self.assertEqual(s3.calls,1)
            self.assertEqual(cached_bytes(scene,manifest.parent),4)
            download_scene(s3,scene,cfg.raw_dir,cfg)
            self.assertEqual(s3.calls,1)
            file=manifest.parent/'file.nc'
            file.write_bytes(b'a')
            with self.assertRaises(IOError): read_manifest(manifest)
            download_scene(s3,scene,cfg.raw_dir,cfg)
            self.assertEqual(s3.calls,2)
            self.assertEqual(read_manifest(manifest)['object_sizes'],[4])

    def test_download_does_not_publish_incomplete_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=StorageConfig(root/'raw',root/'processed',root/'export',1,0)
            scene=Scene('goes16','noaa-goes16','pfx',utc_time('2020-10-29T16:40:00Z'),
                        ('pfx/bad.nc',),5,'ABI-L2-MCMIPF',(5,))
            with self.assertRaises(IOError): download_scene(MockS3(payload=b'bad'),scene,cfg.raw_dir,cfg)
            self.assertFalse((cfg.raw_dir/scene.scene_id/'bad.nc').exists())

    def test_himawari_duplicate_segment_rejected(self):
        prefix='AHI-L1b-FLDK/2020/10/29/1640/'
        objects=[{'Key':prefix+f'HS_H08_20201029_1640_B13_FLDK_R20_S{i:02d}10.DAT.bz2','Size':10} for i in range(1,11)]
        objects[9]={'Key':prefix+'HS_H08_20201029_1640_B13_FLDK_R20_S0110.DAT.bz2','Size':10}
        with self.assertRaises(FileNotFoundError):
            himawari_scene(MockS3(objects),utc_time('2020-10-29T16:40:00Z'),('B13',),10)

if __name__ == '__main__':
    unittest.main()
