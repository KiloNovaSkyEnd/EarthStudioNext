from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
from PIL import Image

from ges.catalog import utc_time
from ges.render import combine_images


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = self.root / 'a.png'
        self.b = self.root / 'b.png'
        self.out = self.root / 'overlay.png'
        for path, stamp, satellite in [(self.a, '2020-10-29T16:40:00Z', 'himawari8'),
                                        (self.b, '2020-10-29T16:40:18.9Z', 'goes16')]:
            Image.new('RGBA', (4, 2), (0, 0, 0, 0)).save(path)
            path.with_suffix('.json').write_text(json.dumps({
                'projection':'EPSG:4326', 'extent_wsen':[-180,-90,180,90],
                'width':4, 'height':2, 'product':'ir-gray',
                'source_satellite':satellite, 'observed_utc':stamp}),encoding='utf-8')

    def change_meta(self, path, **kwargs):
        meta = json.loads(path.with_suffix('.json').read_text())
        meta.update(kwargs)
        path.with_suffix('.json').write_text(json.dumps(meta))

    def test_priority_coverage_index_and_fractional_offsets(self):
        with Image.open(self.a) as image:
            image.putpixel((0, 0), (10, 10, 10, 255)); image.save(self.a)
        with Image.open(self.b) as image:
            image.putpixel((0, 0), (20, 20, 20, 255))
            image.putpixel((1, 0), (30, 30, 30, 255)); image.save(self.b)
        combine_images([self.a, self.b], self.out)
        with Image.open(self.out) as image:
            self.assertEqual(image.getpixel((0,0)), (10,10,10,255))
            self.assertEqual(image.getpixel((1,0)), (30,30,30,255))
            self.assertEqual(image.getpixel((2,0))[3], 0)
        with Image.open(self.root / 'overlay_source_index.png') as image:
            np.testing.assert_array_equal(np.asarray(image)[0], [1,2,0,0])
        meta = json.loads(self.out.with_suffix('.json').read_text())
        self.assertEqual(meta['observed_pixels'], 2)
        self.assertEqual(meta['missing_pixels'], 6)
        self.assertEqual(meta['max_source_time_span_seconds'], 18.9)
        self.assertEqual(meta['sources'][1]['offset_seconds'], 18.9)
        self.assertEqual(meta['sources'][1]['overlap_pixels'], 1)
        self.assertEqual(meta['sources'][1]['contributed_pixels'], 1)
        self.assertFalse(meta['is_interpolated_time'])

    def test_explicit_reference_time(self):
        combine_images([self.a,self.b], self.out, utc_time('2020-10-29T16:45:00Z'))
        meta = json.loads(self.out.with_suffix('.json').read_text())
        self.assertEqual(meta['sources'][0]['offset_seconds'], -300)
        self.assertAlmostEqual(meta['sources'][1]['offset_seconds'], -281.1)

    def test_rejects_missing_provenance(self):
        self.b.with_suffix('.json').unlink()
        with self.assertRaises(FileNotFoundError):
            combine_images([self.a,self.b], self.out)
        self.assertFalse(self.out.exists())

    def test_rejects_incompatible_grid_product_and_time(self):
        original = self.b.with_suffix('.json').read_text()
        for update in [{'projection':'EPSG:3857'}, {'product':'rgb'},
                       {'product':'ir-night-display'},
                       {'display_recipe':'ir-gray-cold-white-v2'},
                       {'extent_wsen':[0,-90,360,90]}, {'width':8},
                       {'observed_utc':'2020-10-29T16:40:00'}]:
            self.b.with_suffix('.json').write_text(original)
            self.change_meta(self.b, **update)
            with self.assertRaises(ValueError):
                combine_images([self.a,self.b], self.out)
            self.assertFalse(self.out.exists())

    def test_rejects_opaque_rgb_and_partial_alpha(self):
        for mode, color in [('RGB',(10,10,10)), ('RGBA',(10,10,10,128))]:
            Image.new(mode,(4,2),color).save(self.b)
            with self.assertRaises(ValueError):
                combine_images([self.a,self.b], self.out)

    def test_output_cannot_overwrite_source_or_source_index(self):
        for out in [self.a, self.a.with_suffix('.json')]:
            with self.assertRaises(ValueError):
                combine_images([self.a,self.b], out)


if __name__ == '__main__':
    unittest.main()
