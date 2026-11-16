import hashlib
import io
import json
from pathlib import Path
import types
import unittest
import uuid
from unittest.mock import patch
from ges_next.production.assets import write_json
from ges_next.production.rebuild_recipe import validate,create,BANDS
from ges_next.production.reacquire import restore


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.root=(Path('reports/rebuild_fixtures')/uuid.uuid4().hex).resolve();self.root.mkdir(parents=True)
        self.rows=[];self.payloads={};self.inputs=[]
        for band in BANDS:
            for segment in range(1,11):
                name=f'HS_H09_20261020_1300_{band}_FLDK_R10_S{segment:02}10.DAT.bz2'
                key='AHI-L1b-FLDK/2026/10/20/1300/'+name;payload=name.encode()
                row=dict(bucket='noaa-himawari9',key=key,bytes=len(payload),etag='"pinned"',sha256=hashlib.sha256(payload).hexdigest())
                self.rows.append(row);self.payloads[key]=payload
                source=self.root/name;source.write_bytes(payload)
                write_json(Path(str(source)+'.json'),dict(**{k:v for k,v in row.items() if k!='bucket'},source='NOAA anonymous S3 Himawari9'))
                self.inputs.append(dict(source=str(source),bytes=len(payload),sha256=row['sha256']))
        self.recipe=self.root/'recipe.json'
        write_json(self.recipe,dict(schema='earthstudio.h9.rebuild.v1',utc='2026-10-20T13:00:00Z',inputs=self.rows))
        self.calls=[]
        def get_object(**kwargs):
            self.calls.append(kwargs);self.assertEqual(kwargs['IfMatch'],'"pinned"')
            return dict(Body=io.BytesIO(self.payloads[kwargs['Key']]))
        self.client=types.SimpleNamespace(get_object=get_object)

    def test_restore_only_selected_scan_and_resume(self):
        destination=self.root/'candidate'
        with patch('shutil.disk_usage',return_value=types.SimpleNamespace(free=100*1024**3)):
            restore(self.recipe,destination,self.client)
            self.assertEqual(len(self.calls),60)
            restore(self.recipe,destination,self.client)
        self.assertEqual(len(self.calls),60)
        self.assertEqual(len(list((destination/'raw/20261020T1300Z').glob('*.bz2'))),60)
        self.assertEqual(len(list((destination/'raw').iterdir())),1)

    def test_insufficient_space_never_downloads(self):
        with patch('shutil.disk_usage',return_value=types.SimpleNamespace(free=0)):
            with self.assertRaises(ValueError):restore(self.recipe,self.root/'full',self.client)
        self.assertEqual(self.calls,[])

    def test_changed_provider_bytes_not_installed(self):
        self.payloads[self.rows[0]['key']]=b'changed'
        with patch('shutil.disk_usage',return_value=types.SimpleNamespace(free=100*1024**3)):
            with self.assertRaises(ValueError):restore(self.recipe,self.root/'candidate',self.client)
        self.assertEqual(list((self.root/'candidate').rglob('*.bz2')),[])

    def test_other_time_and_incomplete_recipe_rejected(self):
        value=json.loads(self.recipe.read_text());value['utc']='2026-10-20T13:10:00Z'
        with self.assertRaises(ValueError):validate(value)
        value=json.loads(self.recipe.read_text());value['inputs'].pop()
        with self.assertRaises(ValueError):validate(value)

    def test_recipe_survives_loss_of_local_inputs(self):
        entry=create(self.root,'2026-10-20T13:00:00Z',self.inputs,dict(quality=95),self.root/'aux')
        for item in self.inputs:Path(item['source']).unlink()  # Only this test's tiny newly-created files.
        value=json.loads((self.root/entry['path']).read_text());validate(value)
        self.assertEqual(len(value['inputs']),60);self.assertEqual(value['profile']['quality'],95)


if __name__=='__main__':unittest.main()
