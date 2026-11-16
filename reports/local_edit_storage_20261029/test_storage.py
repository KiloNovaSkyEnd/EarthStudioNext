import importlib.util,json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
ENGINE=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ENGINE));os.chdir(ENGINE)
spec=importlib.util.spec_from_file_location('legacyfixtures',ENGINE/'tests/test_layered_sequence.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from local_package import build
from local_preview import prepare
class StorageTests(unittest.TestCase):
 def setUp(self):
  self.fixture=fixture.SequenceTests();self.fixture.setUp();self.root=self.fixture.root;self.sources=self.fixture.sources
 def test_local_is_same_file_and_exact_bytes(self):
  out=self.root/'local';m=build(self.sources,out)
  self.assertTrue(m['shared_immutable_assets']);self.assertTrue(os.path.samefile(self.sources[0]/'base.jpg',out/'assets/base/weather_0001.jpg'))
  for item in m['files']:self.assertEqual(fixture.digest(out/item['path']),item['sha256'])
 def test_explicit_copy_is_independent(self):
  out=self.root/'copy';build(self.sources,out,storage='copy');self.assertFalse(os.path.samefile(self.sources[0]/'base.jpg',out/'assets/base/weather_0001.jpg'))
 def test_link_failure_does_not_copy(self):
  out=self.root/'failed'
  with patch('os.link',side_effect=OSError('cross-volume')):
   with self.assertRaisesRegex(ValueError,'no automatic full copy'):build(self.sources,out)
  self.assertFalse((out/'assets/base/weather_0001.jpg').exists())
 def test_local_preview_needs_no_movie(self):
  out=self.root/'preview';build(self.sources,out);m=prepare(out,width=1024)
  self.assertEqual(len(m['frames']),2);self.assertNotIn('videoPreview',m);self.assertFalse((out/'timelapse.mp4').exists())
 def test_no_overwrite(self):
  out=self.root/'safe';build(self.sources,out)
  with self.assertRaises(FileExistsError):build(self.sources,out)
 def test_sources_unchanged(self):
  before={p:fixture.digest(p) for source in self.sources for p in source.iterdir() if p.is_file()}
  build(self.sources,self.root/'local')
  self.assertTrue(all(fixture.digest(p)==h for p,h in before.items()))
 def test_bad_source_rejected(self):
  (self.sources[0]/'base.jpg').write_bytes(b'corrupt')
  with self.assertRaises(ValueError):build(self.sources,self.root/'bad')
if __name__=='__main__':unittest.main()
