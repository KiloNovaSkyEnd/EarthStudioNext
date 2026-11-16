"""Optional hardware parity checks; no network or observation downloads."""
import importlib.util
import unittest
import numpy as np
from ges.earth_validation.fusion import fuse


@unittest.skipUnless(importlib.util.find_spec('cupy'),'CUDA dependencies not installed')
class GPUFusionTests(unittest.TestCase):
    def test_overlap_missing_poles_and_ties_preserve_ownership(self):
        rng=np.random.default_rng(42)
        lon,lat=np.meshgrid(np.linspace(-180,180,161),np.linspace(-90,90,97))
        sources=[]
        for lon0 in (-137,-75,0,41.5,140.7):
            pixels=rng.integers(0,256,(*lon.shape,4),dtype=np.uint8)
            pixels[...,3]=np.where(rng.random(lon.shape)>.2,255,0)
            sources.append((pixels,lon0))
        cpu=fuse(sources,lon,lat); cuda=fuse(sources,lon,lat,backend='cuda')
        np.testing.assert_array_equal(cpu[1],cuda[1])
        np.testing.assert_array_equal(cpu[0][...,3],cuda[0][...,3])
        self.assertLessEqual(np.abs(cpu[0].astype(int)-cuda[0].astype(int)).max(),1)
        tied=fuse([(sources[0][0],0),(sources[1][0],0)],lon,lat,backend='cuda')
        np.testing.assert_array_equal(tied[1],fuse([(sources[0][0],0),(sources[1][0],0)],lon,lat)[1])

    def test_empty_sources_are_missing(self):
        longitude=np.zeros((8,8)); latitude=np.zeros_like(longitude)
        result=fuse([],longitude,latitude,backend='cuda')
        self.assertTrue(all(np.count_nonzero(value)==0 for value in result))

    def test_parallel_cpu_producers_share_bounded_gpu_pool(self):
        from concurrent.futures import ThreadPoolExecutor
        import cupy as cp
        lon,lat=np.meshgrid(np.linspace(-5,5,64),np.linspace(-5,5,64))
        pixels=np.full((64,64,4),255,np.uint8)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:fuse([(pixels,0)],lon,lat,backend='cuda'),range(8)))
        for result in results:
            np.testing.assert_array_equal(result[0],pixels)
        self.assertLessEqual(cp.get_default_memory_pool().total_bytes(),2*1024**3)


if __name__=='__main__': unittest.main()
