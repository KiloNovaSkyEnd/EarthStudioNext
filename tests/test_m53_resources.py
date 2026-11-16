import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ges_next.isolation import require_writable
from ges_next.night_resources import validate,configure,resolve
from ges_next.catalog_cache import CatalogCache
from ges_next.noaa import AHI_BANDS
from ges_next.selection import utc

class ResourceTests(unittest.TestCase):
 def test_registered_external_storage_respects_protected_roots(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);user=base/'user';user.mkdir();external=base/'external'
   with self.assertRaises(ValueError):require_writable(external/'job',workspace=base/'work',user_data=user,protected=[])
   (user/'storage_locations.json').write_text(json.dumps([str(external)]))
   self.assertEqual(require_writable(external/'job',workspace=base/'work',user_data=user,protected=[]),(external/'job').resolve())
   with self.assertRaises(ValueError):require_writable(external/'old',workspace=base/'work',user_data=user,protected=[external/'old'])
 def test_night_missing_fails_before_production(self):
  with tempfile.TemporaryDirectory() as d,patch('ges_next.night_resources.settings',return_value=Path(d)/'settings.json'):
   with self.assertRaises(ValueError):resolve()
 def test_configured_1km_or_500m_references_keep_external_files_read_only(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);tile=root/'tile.tif';tile.write_bytes(b'fixture only; metadata check, not raster validation')
   for w,h in [(86400,43200),(43200,21600)]:
    p=root/f'{w}.vrt';p.write_text(f'<VRTDataset rasterXSize="{w}" rasterYSize="{h}"><SRS>EPSG:4326</SRS><GeoTransform>-180,{360/w},0,90,0,{-180/h}</GeoTransform><VRTRasterBand><SimpleSource><SourceFilename relativeToVRT="1">tile.tif</SourceFilename></SimpleSource></VRTRasterBand></VRTDataset>')
    before=p.read_bytes()
    with patch('ges_next.night_resources.settings',return_value=root/'config.json'):
     configure(p);self.assertEqual(resolve(),p);self.assertEqual(before,p.read_bytes())
     if w==43200:
      with self.assertRaises(ValueError):resolve(metres=500)
     else:self.assertEqual(resolve(metres=500),p)
   tile.unlink()
   with self.assertRaises(ValueError):validate(p)
 def test_import_inventory_direct_file_from_another_storage(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'elsewhere';source.mkdir();file=source/'inventory.json'
   body=dict(project_spec=dict(SatelliteSelection=dict(Mode='manual',Satellites=['himawari9'])),records=[dict(region='向日葵9号',source='himawari9',state='available',requested_utc='2026-10-20T13:00:00Z',native=dict(complete=True,bands=list(AHI_BANDS),keys=['fixture']))])
   file.write_text(json.dumps(body));before=file.read_bytes();cache=CatalogCache(root/'cache')
   cache.import_inventories(file)
   self.assertTrue(cache.query(utc('2026-10-20T13:00Z'),['himawari9'],None,lambda *a:self.fail('Should reuse imported evidence'))['cache_hit'])
   self.assertEqual(before,file.read_bytes());cache.close()

if __name__=='__main__':unittest.main()
