"""Pure-Python import contract checks; actual Blender checks are separate."""
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from blender_make_earth import geographic_position, validate_cloud, validate_output_paths


class BlenderContractTests(unittest.TestCase):
    def test_outputs_preserve_source_texture_and_provenance(self):
        cloud, earth = Path('cloud.png'), Path('earth.png')
        with self.assertRaises(ValueError):
            validate_output_paths(cloud, earth, Path('cloud.blend'), None)
        with self.assertRaises(ValueError):
            validate_output_paths(cloud, earth, Path('earth.blend'), None)
        for preview in [cloud, earth]:
            with self.assertRaises(ValueError):
                validate_output_paths(cloud, earth, Path('preview.blend'), preview)
        validate_output_paths(cloud, earth, Path('preview.blend'), Path('preview.png'))

    def test_geographic_axes_and_poles(self):
        for lon, lat, expected in [(0,0,(1,0,0)), (90,0,(0,1,0)),
                                   (180,0,(-1,0,0)), (0,90,(0,0,1)),
                                   (0,-90,(0,0,-1))]:
            for actual, target in zip(geographic_position(lon,lat,1), expected):
                self.assertAlmostEqual(actual,target,places=12)

    def test_texture_contract_rejects_rgb_wrong_grid_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'texture.png'
            Image.new('RGBA',(4,2)).save(path)
            with self.assertRaises(FileNotFoundError): validate_cloud(path)
            meta={'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':4,'height':2}
            path.with_suffix('.json').write_text(json.dumps(meta))
            self.assertEqual(validate_cloud(path),meta)
            rejected={**meta,'validation_status':'REJECTED: source navigation failure'}
            path.with_suffix('.json').write_text(json.dumps(rejected))
            with self.assertRaises(ValueError):validate_cloud(path)
            path.with_suffix('.json').write_text(json.dumps(meta))
            Image.new('RGB',(4,2)).save(path)
            with self.assertRaises(ValueError): validate_cloud(path)
            Image.new('RGBA',(4,4)).save(path)
            with self.assertRaises(ValueError): validate_cloud(path)
            Image.new('RGBA',(4,2)).save(path)
            meta['projection']='EPSG:3857'
            path.with_suffix('.json').write_text(json.dumps(meta))
            with self.assertRaises(ValueError): validate_cloud(path)


if __name__=='__main__':
    unittest.main()
