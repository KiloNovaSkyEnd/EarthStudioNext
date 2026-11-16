import tempfile,unittest,threading,os,stat
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from ges_next.production.static_night import StaticNight,materialize
from ges_next.production.assets import digest,verify_assets


class StaticNightTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd()/'reports');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.grid=dict(shape=[16,16],extent=[-1,-1,1,1],crs='fixture')
        self.pixels=np.arange(16*16*3,dtype=np.uint8).reshape(16,16,3)
        self.slot=StaticNight({'source':'fixture'},self.grid,95,self.root/'cache')

    def test_once_then_read_only_hardlinks_are_valid_final_assets(self):
        value,reused=self.slot.ensure(self.pixels);self.assertFalse(reused)
        with patch('ges_next.production.jpeg_layers.encode_jpeg',side_effect=AssertionError('reencoded')):
            _,reused=self.slot.ensure();self.assertTrue(reused)
        one=materialize(self.slot.path,self.root/'one','assets/night.jpg',value['asset'])
        two=materialize(self.slot.path,self.root/'two','assets/night.jpg',value['asset'])
        self.assertEqual(one['sharing'],'hardlink');self.assertEqual(two['sharing'],'hardlink')
        self.assertEqual(self.slot.path.stat().st_ino,(self.root/'one/assets/night.jpg').stat().st_ino)
        self.assertTrue(verify_assets(self.root/'one',[one]));self.assertTrue(verify_assets(self.root/'two',[two]))

    def test_cross_volume_or_temporary_fallback_is_independent_copy(self):
        value,_=self.slot.ensure(self.pixels)
        with patch('os.link',side_effect=OSError('other volume')):
            item=materialize(self.slot.path,self.root/'copy','assets/night.jpg',value['asset'])
        self.assertEqual(item['sharing'],'copy')
        item=materialize(self.slot.path,self.root/'scratch','scratch/night.jpg',value['asset'],link=False)
        self.assertEqual((self.root/'scratch/scratch/night.jpg').stat().st_nlink,1)

    def test_reference_grid_and_quality_have_separate_cache_keys(self):
        alternatives=[StaticNight({'source':'other'},self.grid,95,self.root/'cache'),
            StaticNight({'source':'fixture'},dict(self.grid,extent=[-2,-1,1,1]),95,self.root/'cache'),
            StaticNight({'source':'fixture'},self.grid,100,self.root/'cache')]
        self.assertTrue(all(item.key!=self.slot.key for item in alternatives))

    def test_concurrent_publish_encodes_only_once(self):
        from ges_next.production.jpeg_layers import encode_jpeg
        calls=[];lock=threading.Lock()
        def encode(*args,**kwargs):
            with lock:calls.append(1)
            return encode_jpeg(*args,**kwargs)
        with patch('ges_next.production.jpeg_layers.encode_jpeg',side_effect=encode),ThreadPoolExecutor(max_workers=3) as pool:
            result=list(pool.map(lambda _:self.slot.ensure(self.pixels),range(3)))
        self.assertEqual(len(calls),1);self.assertEqual(sum(not reused for _,reused in result),1)

    def test_corruption_and_escaped_paths_are_rejected(self):
        value,_=self.slot.ensure(self.pixels)
        with self.assertRaises(ValueError):materialize(self.slot.path,self.root/'out','../outside.jpg',value['asset'])
        self.slot.path.chmod(stat.S_IWRITE|stat.S_IREAD);self.slot.path.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.slot.lookup()


if __name__=='__main__':unittest.main()
