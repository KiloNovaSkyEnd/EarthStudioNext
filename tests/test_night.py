import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from ges.night import night_cloud_rgba, prepare_night_display
from ges.render import IR_GRAY_RECIPE


class NightTests(unittest.TestCase):
    def test_opacity_is_cold_bright_and_missing_stays_empty(self):
        kelvin=np.array([[193.15,233.15,273.15,293.15,np.nan,193.15]])
        with np.errstate(invalid='raise'):
            rgba=night_cloud_rgba(kelvin,np.array([[True,True,True,True,True,False]]))
        alpha=rgba[0,:,3]
        self.assertEqual(alpha[0],255)
        self.assertGreater(alpha[1],alpha[2])
        np.testing.assert_array_equal(alpha[3:],[0,0,0])

    def test_invalid_opacity_parameters(self):
        for kwargs in [{'warm_k':200,'cold_k':250},{'gamma':0},{'cold_k':np.nan}]:
            with self.assertRaises(ValueError): night_cloud_rgba([[230]],[[True]],**kwargs)
        with self.assertRaises(ValueError): night_cloud_rgba([[230,250]],[[True]])

    def test_export_separates_coverage_from_artistic_opacity_and_static_lights(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder); ir=folder/'ir.png'; lights=folder/'lights.png'
            raw=np.zeros((256,512,4),dtype=np.uint8); raw[...,3]=255
            raw[0,0,3]=0  # missing measurement, elsewhere warm observed background.
            Image.fromarray(raw).save(ir)
            meta={'product':'ir-gray','display_recipe':IR_GRAY_RECIPE,'display_mapping':{'cold_white_c':-100,'warm_black_c':45},
                  'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],
                  'width':512,'height':256,'observed_utc':'2020-10-29T16:40:00Z'}
            ir.with_suffix('.json').write_text(json.dumps(meta))
            Image.new('RGB',(512,256),(100,100,100)).save(lights)
            ref={'kind':'static reference night-lights composite, not contemporaneous with satellite clouds',
                 'reference_year':2016,'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],
                 'width':512,'height':256}
            lights.with_suffix('.json').write_text(json.dumps(ref))
            out=prepare_night_display(ir,lights,folder/'derived')
            display=json.loads(out.with_suffix('.json').read_text())
            self.assertFalse(display['is_opacity_retrieval'])
            with Image.open(out.parent/display['source_ir_coverage']) as im:
                self.assertEqual(im.getpixel((0,0)),0)
                self.assertEqual(im.getpixel((1,0)),255)
            with Image.open(out) as im:
                self.assertEqual(im.getpixel((1,0))[3],0)  # observed warm != missing.
            with Image.open(out.parent/display['night_surface']) as im:
                self.assertEqual(im.getpixel((0,0)),(24,11,35))
                # At this UTC the equator near 140 E is dark, 75 W is daytime.
                self.assertEqual(im.getpixel((455,128)),(100,100,100))
                self.assertEqual(im.getpixel((149,128)),(4,5,12))
            meta['display_recipe']='old-warm-white'
            ir.with_suffix('.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError): prepare_night_display(ir,lights,folder/'rejected')


if __name__=='__main__': unittest.main()
