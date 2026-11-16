import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import numpy as np
from PIL import Image
from ges.blend import view_weight,edge_weight,blend_ir
from ges.render import IR_GRAY_RECIPE

GEOMETRY={'longitude':0,'latitude':0,'altitude_m':35785831,'earth_radius_m':6378169}


class BlendTests(unittest.TestCase):
    def test_angle_prefers_nadir_and_is_periodic_at_dateline(self):
        w=view_weight([0,40,80],0,GEOMETRY)
        self.assertGreater(w[0],w[1]);self.assertGreater(w[1],w[2])
        np.testing.assert_allclose(view_weight(-180,20,GEOMETRY),view_weight(180,20,GEOMETRY))

    def test_edge_feather_wraps_longitude_and_never_fills_missing(self):
        mask=np.ones((20,40),dtype=bool);mask[:,15:25]=False
        w=edge_weight(mask,4)
        self.assertFalse(w[~mask].any())
        self.assertEqual(w[10,0],1);self.assertEqual(w[10,-1],1)
        self.assertLess(w[10,14],w[10,11])

    def test_overlap_is_smooth_single_source_exact_and_holes_stay_missing(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);records=[]
            for number,lon,value in [(1,-40,60),(2,40,180)]:
                a=np.zeros((256,512,4),dtype=np.uint8);a[...,:3]=value;a[...,3]=255
                a[:20,:,3]=0
                if number==1:a[:,370:,3]=0
                else:a[:,:140,3]=0
                p=root/f'source{number}.png';Image.fromarray(a).save(p)
                meta={'width':512,'height':256,'product':'ir-gray','display_recipe':IR_GRAY_RECIPE,
                      'display_mapping':{'cold_white_c':-100,'warm_black_c':45},'projection':'EPSG:4326',
                      'extent_wsen':[-180,-90,180,90],'observed_utc':'2020-10-29T16:40:00Z'}
                p.with_suffix('.json').write_text(json.dumps(meta))
                records.append({'image':str(p),'geometry':{**GEOMETRY,'longitude':lon}})
            out=blend_ir(records,root/'derived.png','2020-10-29T16:40:00Z',16)
            result=np.asarray(Image.open(out))
            self.assertFalse(result[:20,:,3].any())
            self.assertTrue((result[128,:140,0]==60).all());self.assertTrue((result[128,370:,0]==180).all())
            line=result[128,140:370,0].astype(float)
            self.assertGreater(line[100],60);self.assertLess(line[100],180)
            self.assertLess(np.max(np.abs(np.diff(line))),5)
            meta=json.loads(out.with_suffix('.json').read_text())
            self.assertFalse(meta['is_gap_filled']);self.assertFalse(meta['is_radiometrically_calibrated_fusion'])
            with self.assertRaises(ValueError):blend_ir(records,Path(records[0]['image']),'2020-10-29T16:40:00Z')
