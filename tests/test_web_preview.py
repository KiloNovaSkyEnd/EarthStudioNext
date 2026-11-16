import unittest,tempfile,io,json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from PIL import Image
from ges_next.web_preview import prepare,compress_preview

class WebPreviewTests(unittest.TestCase):
    def test_vrt_halo_crop_and_multiband_pages(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,green in [('left.tif',50),('right.tif',150)]:
                pixels=np.full((4,4,4),255,np.uint8);pixels[:3,1:3,1:3]=0;pixels[1,1:3,1:3]=green
                with rasterio.open(root/name,'w',driver='GTiff',width=4,height=4,count=4,dtype='uint8') as dst:dst.write(pixels)
            bands=[]
            for band in range(1,5):
                sources=''.join(f'<SimpleSource><SourceFilename relativeToVRT="1">{name}</SourceFilename><SourceBand>{band}</SourceBand><SrcRect xOff="1" yOff="1" xSize="2" ySize="2"/><DstRect xOff="{x}" yOff="0" xSize="2" ySize="2"/></SimpleSource>' for name,x in [('left.tif',0),('right.tif',2)])
                bands.append(f'<VRTRasterBand dataType="Byte" band="{band}">{sources}</VRTRasterBand>')
            master=root/'master.vrt';master.write_text('<VRTDataset rasterXSize="4" rasterYSize="2"><SRS>EPSG:4326</SRS><GeoTransform>-180,90,0,90,0,-90</GeoTransform>'+''.join(bands)+'</VRTDataset>')
            originals={p.name:p.read_bytes() for p in root.glob('*.tif')}
            path,_=prepare(master,128);preview=np.asarray(Image.open(path))
            self.assertEqual(preview[32,32,1],50);self.assertEqual(preview[32,96,1],150)
            self.assertEqual(preview[32,32,0],0)
            self.assertTrue(all((root/name).read_bytes()==content for name,content in originals.items()))

    def test_orientation_alpha_and_native_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            master=Path(temp)/'master.tif';pixels=np.zeros((4,180,360),np.uint8)
            pixels[0]=np.arange(180,dtype=np.uint8)[:,None];pixels[1,:,:180]=80;pixels[1,:,180:]=160
            pixels[3]=255;pixels[3,:,:20]=0
            with rasterio.open(master,'w',driver='GTiff',width=360,height=180,count=4,dtype='uint8',crs='EPSG:4326',transform=from_bounds(-180,-90,180,90,360,180)) as dst:dst.write(pixels)
            original=master.read_bytes();path,info=prepare(master,128)
            preview=np.asarray(Image.open(path));self.assertEqual(preview.shape,(64,128,4))
            self.assertEqual(preview[32,32,1],80);self.assertEqual(preview[32,96,1],160)
            self.assertLess(preview[5,32,0],preview[58,32,0]);self.assertEqual(preview[32,1,3],0)
            self.assertTrue(np.all(preview[32,1,:3]==0));self.assertEqual(master.read_bytes(),original)
            self.assertTrue(info['display_only']);self.assertEqual(prepare(master,128)[0],path)
            web,compressed=compress_preview(path,info)
            decoded=np.asarray(Image.open(web).convert('RGBA'))
            self.assertTrue(np.array_equal(decoded[:,:,3],preview[:,:,3]))
            self.assertTrue(compressed['display_only']);self.assertEqual(compressed['format'],'WEBP')
            self.assertEqual(master.read_bytes(),original)

if __name__=='__main__':unittest.main()
