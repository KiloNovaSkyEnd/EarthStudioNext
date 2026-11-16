import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ges.native_bridge import scan
from ges_next.inventory_selection import groups,query,selection,SATELLITES
from ges_next.selection import utc


class InventorySelectionTests(unittest.TestCase):
    def project(self,ids):
        return dict(Id='selection-test',StartUtc='2026-10-20T13:00:00Z',EndUtc='2026-10-21T01:00:00Z',IntervalMinutes=10,
                    SatelliteSelection=dict(Mode='manual',Satellites=ids))

    def test_single_multiple_all_query_only_selected(self):
        for ids in [['himawari9'],['himawari9','goes19'],list(SATELLITES)]:
            project=self.project(ids);calls=[]
            def fake(when,choices,client):
                self.assertEqual(len(choices),1);calls.extend(choices)
                return dict(source=choices[0],state='missing')
            with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
                path=scan(project,Path(folder)/'inventory',query_fn=fake,client=object(),groups_fn=lambda when:groups(project,when))
                result=json.loads(Path(path).read_text(encoding='utf-8'))
                self.assertEqual(len(calls),73*len(ids));self.assertEqual(set(calls),set(ids))
                self.assertEqual(result['expected_records'],73*len(ids))
                self.assertEqual(result['satellite_selection']['Satellites'],ids)

    def test_unselected_fallback_never_probed(self):
        calls=[]
        def unavailable(client,candidate,when):
            calls.append(candidate.satellite);raise FileNotFoundError()
        result=query(utc('2026-10-20T13:00:00Z'),['goes16'],object(),None,probe_fn=unavailable)
        self.assertEqual(calls,['goes16']);self.assertEqual(result['state'],'missing')

    def test_inapplicable_date_does_not_substitute(self):
        def fail(*args): self.fail('Unexpected provider request')
        result=query(utc('2026-10-20T13:00:00Z'),['himawari8'],object(),fail,probe_fn=fail)
        self.assertEqual(result['state'],'not-applicable')

    def test_fci_does_not_query_old_slot(self):
        def fail(*args): self.fail('Unselected old platform requested')
        result=query(utc('2026-10-20T13:00:00Z'),['meteosat12'],object(),fail,probe_fn=fail)
        self.assertEqual(result['state'],'unavailable')

    def test_old_project_requires_scope_before_search(self):
        with self.assertRaises(ValueError): groups({},utc('2026-10-20T13:00:00Z'))
        with self.assertRaises(ValueError): groups({'SatelliteSelection':dict(Mode='auto',Satellites=[])},utc('2026-10-20T13:00:00Z'))
        explicit={'SatelliteSelection':dict(Mode='auto',Preset='global',Satellites=[])}
        self.assertEqual(len(groups(explicit,utc('2026-10-20T13:00:00Z'))),5)

    def test_invalid_selection(self):
        for value in [[],['unknown'],['himawari9','himawari9']]:
            with self.assertRaises(ValueError): selection(self.project(value))

    def test_real_next_bridge_uses_selection_from_native_request(self):
        from ges import native_bridge
        from ges_next import bridge
        import uuid
        destination=Path('reports/satellite_selection_fixtures')/uuid.uuid4().hex
        project=self.project(['himawari9']);calls=[]
        def evidence(client,candidate,when):
            calls.append(candidate.satellite)
            return dict(complete=True,satellite=candidate.satellite,observed_utc=when.isoformat(),
                        keys=[f'H9-{when.isoformat()}'],total_bytes=1)
        request=dict(action='scan',project=project,options=dict(output=str(destination.resolve())))
        with tempfile.TemporaryDirectory() as isolated,patch.dict('os.environ',{'LOCALAPPDATA':isolated}), \
             patch('sys.stdin',io.StringIO(json.dumps(request))),contextlib.redirect_stdout(io.StringIO()), \
             patch('boto3.client',return_value=object()),patch('ges_next.inventory_selection.probe',evidence), \
             patch.object(native_bridge,'scan',native_bridge.scan),patch.object(native_bridge,'candidates',native_bridge.candidates):
            bridge.main()
        data=json.loads((destination/'inventory.json').read_text(encoding='utf-8'))
        self.assertEqual(calls,['himawari9']*73)
        self.assertEqual(data['expected_records'],73)
        self.assertTrue(data['finished'])


if __name__=='__main__': unittest.main()
