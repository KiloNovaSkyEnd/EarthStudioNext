import unittest
from pathlib import Path
import uuid
import numpy as np
from PIL import Image
from ges_next.production.jpeg_layers import encode_jpeg, encode_mask, reconstruct, srgb_to_linear
from ges_next.production.assets import verify_assets
from ges_next.production.h9_source import source_files


class EncodingTests(unittest.TestCase):
    def test_masks_exact_and_jpeg_full_chroma(self):
        root=Path('reports/production_encoding_fixtures')/uuid.uuid4().hex
        rgb=np.zeros((128,128,3),np.uint8);rgb[::2,:,0]=255;rgb[1::2,:,2]=255
        item=encode_jpeg(root,'color.jpg',rgb,100)
        self.assertEqual(item['subsampling'],'4:4:4');self.assertFalse(item['lossless'])
        self.assertTrue(verify_assets(root,[item]))
        mask=np.arange(65536,dtype=np.uint16).reshape(256,256)
        entry=encode_mask(root,'mask.png',mask,'test')
        with Image.open(root/'mask.png') as image: np.testing.assert_array_equal(mask,np.asarray(image))
        self.assertTrue(verify_assets(root,[entry]))

    def test_exact_transfer_and_independent_light(self):
        base=np.full((1,1,3),32,np.uint8);night=np.full((1,1,3),128,np.uint8)
        mask=np.full((1,1),65535,np.uint16)
        np.testing.assert_allclose(reconstruct(base,night,mask,0),base/255,atol=1e-7)
        np.testing.assert_allclose(reconstruct(base,night,mask,1),160/255,atol=1e-7)
        np.testing.assert_allclose(srgb_to_linear([0,.04045,1]),[0,.04045/12.92,1],atol=1e-12)

    def test_reject_non_utc_or_partial_scan(self):
        for utc in ['2026-10-20T13:00:00','2026-10-20T13:00:00+01:00','2026-10-20T13:01:00Z']:
            with self.assertRaises(ValueError): source_files('.',utc)


if __name__=='__main__': unittest.main()
