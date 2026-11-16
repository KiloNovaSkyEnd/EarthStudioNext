"""Lossless overflow, unpickleable task objects and actual Dask scheduler use."""
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import unittest
import dask
import dask.array as da
import numpy as np
from ges.earth_validation.spill import ArraySpillCache
from ges.earth_validation.spill import bounded_compute
from unittest.mock import patch
from types import SimpleNamespace


class SpillTests(unittest.TestCase):
    def test_opt_in_threads_respect_physical_and_commit_reserves(self):
        gib=1024**3
        for available,commit_free,requested,expected in [(14*gib,10*gib,6,6),(8*gib,10*gib,6,4),(5*gib,10*gib,6,1),(14*gib,2*gib,6,1),(14*gib,10*gib,None,2)]:
            with self.subTest(available=available,commit=commit_free,requested=requested),TemporaryDirectory() as folder:
                with patch('ges.earth_validation.resources.commit_usage',return_value=dict(available_bytes=commit_free)),patch('ges.earth_validation.resources.psutil.virtual_memory',return_value=SimpleNamespace(available=available)):
                    with bounded_compute(folder,workers=requested):
                        self.assertEqual(dask.config.get('num_workers'),expected)
    def test_ssd_budget_overflow_falls_back_without_changing_values(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary); hdd=root/'hdd'; ssd=root/'ssd'; hdd.mkdir(); ssd.mkdir()
            cache=ArraySpillCache(hdd,limit=0,fast_folder=ssd,fast_limit=8192,fast_reserve=0)
            small=np.arange(32,dtype=np.float64); large=np.arange(2048,dtype=np.float64)
            cache['small']=small; cache['large']=large
            self.assertEqual(cache.slow['small'][0].parent,ssd)
            self.assertEqual(cache.slow['large'][0].parent,hdd)
            np.testing.assert_array_equal(cache['small'],small)
            np.testing.assert_array_equal(cache['large'],large)
            del cache['small']; self.assertEqual(cache.fast_live_bytes,0)
            del cache['large']; del cache

    def test_lossless_overflow_nan_payload_and_dtype(self):
        with TemporaryDirectory() as temporary:
            cache=ArraySpillCache(temporary,limit=16)
            value=np.arange(64,dtype=np.float64).reshape(8,8)
            value[1,2]=np.nan
            cache['source']=value
            actual=cache['source']
            self.assertEqual(actual.dtype,value.dtype)
            np.testing.assert_array_equal(actual.view(np.uint64),value.view(np.uint64))
            self.assertLessEqual(cache.memory_bytes,16)
            self.assertGreater(cache.disk_bytes,0)
            del actual
            del cache['source']
            self.assertEqual(len(cache),0)

    def test_unpickleable_objects_stay_in_ram(self):
        class Store:
            def __reduce__(self): raise AssertionError('Must not pickle a live TIFF or tree')
        with TemporaryDirectory() as temporary:
            cache=ArraySpillCache(temporary,limit=8)
            marker=Store(); cache['tree']=marker; cache['array']=np.arange(100)
            self.assertIs(cache['tree'],marker)

    def test_shared_task_graph_with_tiny_cache_matches_plain_scheduler(self):
        with TemporaryDirectory() as temporary:
            cache=ArraySpillCache(temporary,limit=1024)
            data=da.arange(128*128,dtype='float64').reshape(128,128).rechunk((16,16))
            result=da.sin(data/13)+data*.25
            expected=result.compute(scheduler='threads',num_workers=2)
            with dask.config.set(cache=cache):
                actual=result.compute(scheduler='threads',num_workers=2)
            np.testing.assert_array_equal(actual,expected)
            self.assertGreater(cache.written_bytes,0)
            self.assertLessEqual(cache.memory_bytes,1024)
            del cache,actual

    def test_import_time_geometry_chunks_are_512(self):
        code=('from ges.earth_validation import bootstrap; import pyresample; '
              'from pyresample import kd_tree; '
              'assert pyresample.CHUNK_SIZE == kd_tree.CHUNK_SIZE == 512')
        subprocess.run([sys.executable,'-c',code],check=True,capture_output=True)
