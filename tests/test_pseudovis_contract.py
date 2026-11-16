"""Catalog/identity fixtures only; no model inference or scientific image claims."""
import copy,json,unittest
from pathlib import Path
from ges_next.algorithms.pseudovis_contract import assess_step,cache_identity,validate_proposal
from ges_next.production.rebuild_recipe import BANDS

class PseudoVisContractTests(unittest.TestCase):
    def setUp(self):
        self.proposal=json.loads(Path('resources/proposals/night_pseudovis_v9.json').read_text(encoding='utf-8'))
        self.step=dict(utc='2026-10-20T15:20:00Z',objects=[dict(bucket='fixture',key=f'HS_H09_20261020_1520_{b}_FLDK_R20_S{s:02}10.DAT.bz2',bytes=1,etag='fixture') for b in BANDS for s in range(1,11)])
    def test_current_plan_requires_six_extra_bands_and_sixty_objects(self):
        a=assess_step(self.step,self.proposal,BANDS)
        self.assertEqual(a['additional_objects_per_scan'],60);self.assertEqual(a['minimum_combined_objects_per_scan'],120)
        self.assertFalse(a['input_coverage_complete']);self.assertFalse(a['integration_ready'])
    def test_complete_catalog_inputs_do_not_imply_scientific_acceptance(self):
        all_bands=set(BANDS)|set(self.proposal['required_ir_bands'])
        self.step['objects']=[dict(bucket='fixture',key=f'HS_H09_20261020_1520_{b}_FLDK_R20_S{s:02}10.DAT.bz2',bytes=1,etag='fixture') for b in all_bands for s in range(1,11)]
        a=assess_step(self.step,self.proposal,BANDS);self.assertTrue(a['input_coverage_complete']);self.assertFalse(a['enabled']);self.assertFalse(a['integration_ready'])
    def test_nearby_frame_is_not_a_valid_source_for_current_frame(self):
        self.step['objects'][-1]['key']=self.step['objects'][-1]['key'].replace('1520','1530')
        a=assess_step(self.step,self.proposal,BANDS);self.assertEqual(len(a['wrong_time_objects']),1);self.assertFalse(a['input_coverage_complete'])
    def test_weight_utc_sun_and_version_changes_have_distinct_cache_identity(self):
        first=cache_identity(self.step,self.proposal,'h9-native-grid')
        for field,value in [('weights_sha256','a'*64),('version','next'),('fixed_virtual_sun',dict(sza=40,azimuth=-70))]:
            proposal=copy.deepcopy(self.proposal);proposal[field]=value
            self.assertNotEqual(first,cache_identity(self.step,proposal,'h9-native-grid'))
        other=copy.deepcopy(self.step);other['utc']='2026-10-20T15:30:00Z'
        self.assertNotEqual(first,cache_identity(other,self.proposal,'h9-native-grid'))
    def test_preparation_cannot_enable_algorithm_or_accept_unpinned_weights(self):
        p=copy.deepcopy(self.proposal);p['enabled']=True
        with self.assertRaises(ValueError):validate_proposal(p)
        p=copy.deepcopy(self.proposal);p['weights_sha256']='latest'
        with self.assertRaises(ValueError):validate_proposal(p)

if __name__=='__main__':unittest.main()
