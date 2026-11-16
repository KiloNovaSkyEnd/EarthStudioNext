import copy
from datetime import datetime
import json
from pathlib import Path
import unittest

from ges.catalog import utc_time
from ges.meteosat import select_observation


class MeteosatTests(unittest.TestCase):
    def fixture(self,service='zero'):
        return json.loads((Path(__file__).parent/'fixtures'/f'meteosat_{service}_20201029.json').read_text())

    def test_real_historical_intervals_preferred_over_filename_end_time(self):
        for service,platform in [('zero','MSG4'),('iodc','MSG1')]:
            result=select_observation(self.fixture(service),utc_time('2020-10-29T16:40:00Z'),service)
            self.assertEqual(result['platform'],platform)
            self.assertTrue(result['scan_contains_reference'])
            self.assertIn('202010291642',result['product_id'])
            self.assertTrue(result['scan_start_utc'].startswith('2020-10-29T16:30:10.'))
            self.assertTrue(result['scan_end_utc'].startswith('2020-10-29T16:42:'))
            self.assertLess(result['start_offset_seconds'],0)
            self.assertGreater(result['end_offset_seconds'],0)
            self.assertFalse(result['downloaded'])
            self.assertFalse(result['render_verified'])
            self.assertIn('NOT verified',result['catalog_size_unit'])

    def test_nearest_outside_scan_and_no_observation(self):
        result=select_observation(self.fixture(),utc_time('2020-10-29T16:44:00Z'),'zero',2)
        self.assertFalse(result['scan_contains_reference'])
        self.assertTrue(result['scan_start_utc'].startswith('2020-10-29T16:45:'))
        with self.assertRaises(FileNotFoundError):
            select_observation(self.fixture(),utc_time('2020-10-30T16:40:00Z'),'zero')

    def test_rejects_incomplete_catalog_and_naive_time(self):
        data=self.fixture();data['totalResults']=len(data['features'])+1
        with self.assertRaises(ValueError): select_observation(data,utc_time('2020-10-29T16:40:00Z'),'zero')
        with self.assertRaises(ValueError): select_observation(self.fixture(),datetime(2020,10,29,16,40),'zero')

    def test_rejects_wrong_collection_host_and_reverse_interval(self):
        when=utc_time('2020-10-29T16:40:00Z')
        with self.assertRaises(FileNotFoundError): select_observation(self.fixture('iodc'),when,'zero')
        data=self.fixture()
        for feature in data['features']:
            feature['properties']['links']['data'][0]['href']='https://example.com/file'
        with self.assertRaises(ValueError): select_observation(data,when,'zero')
        data=self.fixture()
        data['features'][0]['properties']['date']='2020-10-30T00:00:00Z/2020-10-29T00:00:00Z'
        with self.assertRaises(ValueError): select_observation(data,when,'zero')


if __name__=='__main__': unittest.main()
