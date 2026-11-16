"""Small offline fixtures; never fetch real satellite data in tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from pyresample import create_area_def
from ges.earth_validation.project import timeline, initialize
from ges.earth_validation.archive import fetch, target_for
from ges.earth_validation.material import sample_window
from ges.earth_validation.autoprocess import audit_archive
from ges.earth_validation.io_paths import reader_paths


class Body:
    def __init__(self, value): self.value = value
    def iter_chunks(self, chunk_size): yield self.value
    def close(self): pass


class Client:
    def get_object(self, **options):
        self.options = options
        start = int(options['Range'].split('=')[1].split('-')[0])
        return {'ContentLength':4-start, 'Body':Body(b'abcd'[start:])}


class ValidationTests(unittest.TestCase):
    def test_automatic_processing_rejects_partial_or_unreceipted_archive(self):
        with TemporaryDirectory() as tmp:
            row = {'provider':'s3','sensor':'ahi','scene_id':'sample','key':'obj','size':4,'etag':'x'}
            plan = {'records':[row]}
            self.assertEqual(len(audit_archive(tmp, plan)), 1)
            path = target_for(tmp, row)
            path.parent.mkdir(parents=True)
            path.write_bytes(b'abcd')
            self.assertEqual(len(audit_archive(tmp, plan)), 1)
            receipt = path.with_suffix('.receipt.json')
            receipt.write_text(json.dumps({'size':4,'etag':'x','sha256':'a'*64}))
            self.assertEqual(audit_archive(tmp, plan), [])
            path.write_bytes(b'abc')
            self.assertEqual(len(audit_archive(tmp, plan)), 1)

    def test_reader_alias_preserves_bytes_and_rejects_existing_other_file(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.nc'
            source.write_bytes(b'fixture')
            paths = reader_paths(tmp, 'fixture', [source])
            self.assertTrue(paths[0].samefile(source))
            self.assertEqual(paths[0].read_bytes(), b'fixture')

    def test_fixed_minus_six_window_includes_73_nominal_frames(self):
        config = {'start_utc':'2022-08-31T17:00:00Z','end_utc':'2022-09-01T05:00:00Z','interval_minutes':10}
        stamps = timeline(config)
        self.assertEqual(len(stamps),73)
        self.assertEqual(stamps[0].hour,17)
        self.assertEqual((stamps[-1].day,stamps[-1].hour),(1,5))
        self.assertEqual((stamps[-1]-stamps[0]).total_seconds(),43200)

    def test_resume_preserves_prefix_and_records_hash(self):
        with TemporaryDirectory() as tmp, patch('ges.earth_validation.archive.check_disk'):
            row = {'provider':'s3','sensor':'goes16','scene_id':'sample','key':'folder/object.nc',
                   'size':4,'etag':'"etag"','bucket':'example'}
            target = target_for(tmp,row)
            target.parent.mkdir(parents=True)
            part = target.with_suffix('.nc.part')
            part.write_bytes(b'ab')
            part.with_suffix('.part.origin.json').write_text(json.dumps({
                'size':4,'etag':'"etag"','identity':'folder/object.nc'}))
            client = Client()
            result = fetch(tmp,row,client,None)
            self.assertEqual(client.options['Range'],'bytes=2-')
            self.assertEqual(client.options['IfMatch'],'"etag"')
            self.assertEqual(target.read_bytes(),b'abcd')
            self.assertEqual(len(result['sha256']),64)
            fetch(tmp,row,client,None)
            self.assertEqual(target.read_bytes(),b'abcd')

    def test_committed_wrong_size_is_never_overwritten(self):
        with TemporaryDirectory() as tmp:
            row={'provider':'s3','sensor':'ahi','scene_id':'sample','key':'obj','size':4,'etag':'x'}
            target=target_for(tmp,row);target.parent.mkdir(parents=True);target.write_bytes(b'old')
            with self.assertRaisesRegex(RuntimeError,'preserved'):
                fetch(tmp,row,Client(),None)
            self.assertEqual(target.read_bytes(),b'old')

    def test_native_sampling_matches_raw_grid_and_retains_nan(self):
        area=create_area_def('fixture',{'proj':'geos','lon_0':140.7,'h':35785863,
            'a':6378137,'b':6356752.31414,'sweep':'y'},shape=(16,16),
            area_extent=(-1000000,-1000000,1000000,1000000),units='m')
        values=np.arange(256,dtype=np.float32).reshape(16,16);values[8,8]=np.nan
        longitude,latitude=area.get_lonlats()
        with MemoryFile() as memory:
            with memory.open(driver='GTiff',height=16,width=16,count=1,dtype='float32',
                transform=from_bounds(*area.area_extent,16,16),crs=area.crs) as dataset:
                dataset.write(values,1)
                result=sample_window(dataset,area,longitude,latitude)
                np.testing.assert_array_equal(result,values)
                result=sample_window(dataset,area,np.array([0.]),np.array([0.]))
                self.assertTrue(np.isnan(result[0]))


if __name__=='__main__': unittest.main()
