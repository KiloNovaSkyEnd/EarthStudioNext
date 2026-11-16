"""Queue resolution reuses one verified plan; no science or satellite downloads."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ges_next.layered_sequence.collection import from_queue
from ges_next.production.assets import write_json,digest


class PlanReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path('reports').resolve());self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.plan=dict(project=dict(IntervalMinutes=10),steps=[dict(utc=f'2026-10-20T13:{m}:00Z') for m in ['00','10','20']])
        for step in self.plan['steps']:
            p=self.root/'steps'/step['utc'].replace('-','').replace(':','');p.mkdir(parents=True);(p/'commit.json').write_text('{}')
        self.save()

    def save(self):
        write_json(self.root/'plan.json',self.plan)
        write_json(self.root/'state.json',dict(plan_sha256=digest(self.root/'plan.json')))

    def test_plan_is_parsed_once_for_all_steps(self):
        original=Path.read_text;reads=[]
        def read(path,*args,**kwargs):
            if path==self.root/'plan.json':reads.append(path)
            return original(path,*args,**kwargs)
        with patch('pathlib.Path.read_text',read),patch('ges_next.layered_sequence.collection.collect',return_value=([],{})):
            paths,step=from_queue(self.root)
        self.assertEqual(step,10);self.assertEqual(len(paths),3);self.assertEqual(len(reads),1)
        self.assertEqual(paths,[self.root/'steps'/s['utc'].replace('-','').replace(':','') for s in self.plan['steps']])

    def test_reused_package_still_verified_and_resolved(self):
        utc=self.plan['steps'][1]['utc'];p=self.root/'prior';p.mkdir();(p/'commit.json').write_text('{}')
        self.plan['reused_packages']={utc:dict(package=str(p),commit_sha256='frozen')};self.save()
        with patch('ges_next.pipeline.extension.verified_reference') as verify,patch('ges_next.layered_sequence.collection.collect',return_value=([],{})):
            paths,_=from_queue(self.root)
        verify.assert_called_once_with(p,utc,'frozen');self.assertEqual(paths[1],p)

    def test_changed_plan_still_rejected_before_collection(self):
        (self.root/'plan.json').write_text('{}')
        with self.assertRaises(ValueError):from_queue(self.root)

    def test_unfinished_interval_still_rejected(self):
        missing=dict(index=2,utc=self.plan['steps'][1]['utc'],missing=True,source=None)
        with patch('ges_next.layered_sequence.collection.collect',return_value=([missing],{})):
            with self.assertRaisesRegex(ValueError,'未完成扫描'):from_queue(self.root)


if __name__=='__main__':unittest.main()
