from datetime import datetime, timezone
from pathlib import Path
import unittest
from ges.catalog import utc_time, selected_himawari, himawari_scene, goes_scene
from ges.render import ir_to_rgba, combine_images
from PIL import Image
import numpy as np
import tempfile
import json

class FakePager:
    def __init__(self,objects): self.objects=objects
    def paginate(self,**kwargs):
        yield {'Contents':[o for o in self.objects if o['Key'].startswith(kwargs['Prefix'])]}
class FakeS3:
    def __init__(self,objects): self.objects=objects
    def get_paginator(self,what): return FakePager(self.objects)

class TestPipeline(unittest.TestCase):
    def test_utc(self):
        with self.assertRaises(ValueError): utc_time('2020-10-29T16:40:00')
        self.assertEqual(utc_time('2020-10-29T16:40:00Z').hour, 16)
    def test_himawari_transition(self):
        self.assertEqual(selected_himawari(datetime(2020,10,29,tzinfo=timezone.utc)),'himawari8')
        self.assertEqual(selected_himawari(datetime(2026,4,12,tzinfo=timezone.utc)),'himawari9')
    def test_himawari_complete(self):
        objs=[{'Key':f'AHI-L1b-FLDK/2020/10/29/1640/HS_H08_20201029_1640_B13_FLDK_R20_S{i:02d}10.DAT.bz2','Size':100+i} for i in range(1,11)]
        scene=himawari_scene(FakeS3(objs),utc_time('2020-10-29T16:40:00Z'),('B13',),10)
        self.assertEqual(len(scene.keys),10)
        self.assertEqual(scene.total_bytes,1055)
    def test_himawari_missing_segment(self):
        objs=[{'Key':f'AHI-L1b-FLDK/2020/10/29/1640/HS_H08_20201029_1640_B13_FLDK_R20_S{i:02d}10.DAT.bz2','Size':100} for i in range(1,10)]
        with self.assertRaises(FileNotFoundError):
            himawari_scene(FakeS3(objs),utc_time('2020-10-29T16:40:00Z'),('B13',),10)
    def test_goes(self):
        objs=[{'Key':'ABI-L2-MCMIPF/2020/303/16/OR_ABI-L2-MCMIPF-M6_G16_s20203031640123_e20203031649_c20203031650.nc','Size':123}]
        scene=goes_scene(FakeS3(objs),utc_time('2020-10-29T16:40:00Z'),'goes16')
        self.assertEqual(scene.satellite,'goes16')
    def test_ir_alpha(self):
        p=ir_to_rgba(np.array([[190.,np.nan]],dtype='float32'),'K')
        self.assertEqual(p.getpixel((0,0))[3],255)
        self.assertEqual(p.getpixel((1,0))[3],0)
    def test_priority_overlay(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);a=d/'a.png';b=d/'b.png';o=d/'m.png'
            aa=Image.new('RGBA',(2,1),(0,0,0,0)); aa.putpixel((0,0),(255,255,255,255));aa.save(a)
            bb=Image.new('RGBA',(2,1),(255,0,0,255));bb.save(b)
            for image in [a,b]:
                image.with_suffix('.json').write_text(json.dumps({
                    'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],
                    'width':2,'height':1,'product':'ir-gray',
                    'observed_utc':'2020-10-29T16:40:00Z','source_satellite':'fixture'}))
            combine_images([a,b],o)
            with Image.open(o) as im:
                self.assertEqual(im.getpixel((0,0)),(255,255,255,255))
                self.assertEqual(im.getpixel((1,0)),(255,0,0,255))

if __name__=='__main__':unittest.main()
