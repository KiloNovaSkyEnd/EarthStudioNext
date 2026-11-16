import tempfile,unittest
from pathlib import Path
import numpy as np
from ges_next.production.jpeg_layers import encode_jpeg,encode_mask
from ges_next.performance.quality_strips import measure
from unittest.mock import patch


class QualityStripTests(unittest.TestCase):
    def test_every_valid_pixel_and_extreme_masks_keep_same_metrics(self):
        rng=np.random.default_rng(2)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rgb=rng.integers(0,256,(513,49,3),dtype=np.uint8)
            encode_jpeg(root,'assets/base.jpg',rgb)
            encode_jpeg(root,'assets/night.jpg',rgb[::-1])
            w=rng.integers(0,65536,(513,49),dtype=np.uint16);w[0]=0;w[-1]=65535
            encode_mask(root,'assets/transmission.png',w,'stock-ground-transmission')
            support=rng.integers(0,2,(513,49),dtype=np.uint8)*255
            expected=measure(root,rgb,support,strip_rows=256)
            for rows in (1,32,64,128,256):
                actual=measure(root,rgb,support,strip_rows=rows)
                self.assertEqual(actual['samples'],3*np.count_nonzero(support))
                self.assertEqual(actual['max_channel_error'],expected['max_channel_error'])
                for key in ('psnr_db','valid_rgb_mae'):self.assertAlmostEqual(actual[key],expected[key],places=11)

    def test_invalid_partition_rejected(self):
        with self.assertRaises(ValueError):measure(Path('.'),None,None,strip_rows=0)

    def test_quality_boundaries_recheck_original_partition(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rgb=np.zeros((9,8,3),np.uint8);support=np.full((9,8),255,np.uint8)
            encode_jpeg(root,'assets/base.jpg',rgb)
            encode_jpeg(root,'assets/night.jpg',rgb)
            encode_mask(root,'assets/transmission.png',np.zeros((9,8),np.uint16),'stock-ground-transmission')
            for threshold in (35,37):
                with patch('ges_next.performance.quality_strips.np.log10',return_value=threshold/10):
                    result=measure(root,rgb,support)
                self.assertEqual(result['partition_rows'],256)
                self.assertEqual(result['psnr_db'],threshold)
