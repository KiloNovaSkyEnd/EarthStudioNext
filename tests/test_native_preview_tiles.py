import io, tempfile, unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from PIL import Image
from ges_next.preview_server import native_tile

class NativeTileTests(unittest.TestCase):
    def test_geographic_orientation_alpha_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            master=Path(temp)/'master.tif'
            pixels=np.zeros((4,180,360),np.uint8)
            pixels[0]=np.arange(180,dtype=np.uint8)[:,None]
            pixels[1,:,:180]=80;pixels[1,:,180:]=160
            pixels[3]=255;pixels[3,:,:20]=0
            with rasterio.open(master,'w',driver='GTiff',width=360,height=180,count=4,dtype='uint8',crs='EPSG:4326',transform=from_bounds(-180,-90,180,90,360,180)) as dst:dst.write(pixels)
            before=master.read_bytes()
            left=np.asarray(Image.open(io.BytesIO(native_tile(master,0,0,0))))
            right=np.asarray(Image.open(io.BytesIO(native_tile(master,0,1,0))))
            self.assertEqual(left.shape,(512,512,4))
            self.assertEqual(left[100,5,3],0);self.assertTrue(np.all(left[100,5,:3]==0))
            self.assertEqual(left[256,256,1],80);self.assertEqual(right[256,256,1],160)
            self.assertLess(left[10,256,0],left[500,256,0])
            self.assertEqual(master.read_bytes(),before)
            # A changed source at the same path must invalidate the in-memory tile.
            with rasterio.open(master,'r+') as dst:
                changed=pixels[1].copy();changed[:,180:]=25;dst.write(changed,2)
            refreshed=np.asarray(Image.open(io.BytesIO(native_tile(master,0,1,0))))
            self.assertEqual(refreshed[256,256,1],25)

if __name__=='__main__':unittest.main()
