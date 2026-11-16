import unittest,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
from ges_next.production import qualified_static as Q
class QualifiedStaticTest(unittest.TestCase):
 def test_pinned_reference_is_reused_and_conflict_is_preserved(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'resources/references/qualified_h9_landmask_v1';source.mkdir(parents=True)
   (source/'grid.npy').write_bytes(b'accepted unknown=255')
   data=dict(files=[dict(path='grid.npy',sha256=hashlib.sha256((source/'grid.npy').read_bytes()).hexdigest())])
   (source/'manifest.json').write_text(json.dumps(data),encoding='utf-8');sha=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest()
   with patch.object(Q,'ROOT',root),patch.object(Q,'MANIFEST_SHA256',sha):
    cache=root/'cache';Q.seed(cache);Q.seed(cache)
    target=cache/'static_landmask_grids_v1/grid.npy';target.write_bytes(b'unqualified ocean=0')
    with self.assertRaises(ValueError):Q.seed(cache)
    self.assertEqual(target.read_bytes(),b'unqualified ocean=0')
 def test_source_tampering_does_not_seed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'resources/references/qualified_h9_landmask_v1';source.mkdir(parents=True)
   (source/'manifest.json').write_text('{}',encoding='utf-8')
   with patch.object(Q,'ROOT',root),patch.object(Q,'MANIFEST_SHA256','0'*64):
    with self.assertRaises(ValueError):Q.seed(root/'cache')
   self.assertFalse((root/'cache').exists())
