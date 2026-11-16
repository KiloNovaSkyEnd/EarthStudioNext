import copy,json,unittest
from unittest.mock import patch
from pathlib import Path
from ges_next.pipeline.admission import can_start,capacity,GIB
from ges_next.performance.compatibility import permits


class AdmissionTests(unittest.TestCase):
    def test_memory_reservations_include_not_yet_allocated_workers(self):
        self.assertTrue(can_start([],available=18*GIB))
        self.assertFalse(can_start([],available=10*GIB))
        self.assertFalse(can_start([Path('nonexistent-worker')],available=17*GIB))
        self.assertTrue(can_start([Path('nonexistent-worker')],available=20*GIB))

    def test_qualified_runtime_does_not_bypass_unknown_changes_or_profiles(self):
        p=Path('resources/performance/execution_qualification.json')
        value=json.loads(p.read_text());profile=value['profile']
        self.assertTrue(permits(value['previous_runtime'],value['runtime'],profile))
        bad=copy.deepcopy(value['runtime']);bad['ges_next/production/h9_job.py']='changed'
        self.assertFalse(permits(value['previous_runtime'],bad,profile))
        self.assertFalse(permits(value['previous_runtime'],value['runtime'],dict(profile,NightLightMetres=500)))

    def test_additional_exact_upgrade_and_incomplete_proof(self):
        value=json.loads(Path('resources/performance/execution_qualification.json').read_text())
        earlier={'known-version':'frozen-hash'}
        value['additional_previous_runtimes']=[earlier]
        with patch('pathlib.Path.read_text',return_value=json.dumps(value)):
            self.assertTrue(permits(earlier,value['runtime'],value['profile']))
            self.assertFalse(permits({'known-version':'unknown'},value['runtime'],value['profile']))
        value['asset_comparison']=value['asset_comparison'][:1]
        with patch('pathlib.Path.read_text',return_value=json.dumps(value)):
            self.assertFalse(permits(earlier,value['runtime'],value['profile']))


if __name__=='__main__':unittest.main()
