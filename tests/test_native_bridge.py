import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ges.native_bridge import project_times, candidates, scan, main
from ges.catalog import utc_time


class NativeBridgeTests(unittest.TestCase):
    def project(self):
        return {'Id': 'offline-test', 'StartUtc': '2020-10-29T16:00:00Z',
                'EndUtc': '2020-10-29T17:00:00Z', 'IntervalMinutes': 30}

    def test_timeline_and_candidate_directions(self):
        times = project_times(self.project())
        self.assertEqual(len(times), 3)
        self.assertEqual(len(candidates(times[0])), 5)
        self.assertEqual(candidates(times[0])[0][1], ['himawari8'])
        self.assertEqual(candidates(utc_time('2026-01-01T00:00:00Z'))[0][1], ['himawari9'])

    def test_single_frame_explicit_mode_and_range_validation(self):
        project=self.project() | dict(CaptureMode='single',EndUtc=self.project()['StartUtc'])
        self.assertEqual(len(project_times(project)),1)
        with self.assertRaises(ValueError):project_times(project | dict(CaptureMode='sequence'))
        with self.assertRaises(ValueError):project_times(project | dict(CaptureMode='unknown'))
        with self.assertRaises(ValueError):project_times(project | dict(EndUtc=self.project()['EndUtc']))

    def test_bounded_scan_rejects_before_network(self):
        project = self.project() | {'EndUtc': '2023-11-29T00:00:00Z'}
        with self.assertRaises(ValueError):
            scan(project, 'never-created', client=object())

    def test_twelve_and_twentyfour_hour_checks_allow_all_nodes(self):
        for end,expected in [('2026-10-21T01:00:00Z',73),('2026-10-21T13:00:00Z',145)]:
            project=self.project() | {'StartUtc':'2026-10-20T13:00:00Z','EndUtc':end,'IntervalMinutes':10}
            calls=[]
            def offline_query(when,choices,client):
                calls.append(when)
                return {'source':choices[0],'state':'missing'}
            with tempfile.TemporaryDirectory() as root,contextlib.redirect_stdout(io.StringIO()):
                path=scan(project,Path(root)/'inventory',offline_query,object())
                body=json.loads(Path(path).read_text(encoding='utf-8'))
                self.assertEqual(len(set(calls)),expected)
                self.assertEqual(len(body['records']),expected*5)
                self.assertTrue(body['finished'])
                self.assertEqual(body['known_unique_bytes'],0)

    def test_real_inventory_not_inferred_coverage_and_deduplicated_sizes(self):
        def query(when, choices, client):
            if choices == ['iodc']:
                return {'state': 'missing', 'source': 'iodc'}
            if choices == ['zero']:
                return {'source': 'zero', 'bytes': None, 'native': {'product_id': 'same-msg'}}
            return {'source': choices[0], 'bytes': 123, 'native': {'keys': [choices[0] + '-same-file']}}
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            path = scan(self.project(), Path(root) / 'inventory', query, object())
            record = json.loads(Path(path).read_text(encoding='utf-8'))
            self.assertEqual(record['known_unique_bytes'], 369)
            self.assertEqual(record['unknown_sizes'], 3)
            self.assertEqual(len(record['records']), 15)
            self.assertTrue(record['finished'])
            self.assertIn('no downloaded imagery', record['kind'])
            with self.assertRaises(FileExistsError):
                scan(self.project(), Path(root) / 'inventory', query, object())

    def test_interrupted_scan_keeps_atomic_partial_results(self):
        counter = [0]
        def query(when, choices, client):
            counter[0] += 1
            if counter[0] == 3:
                raise KeyboardInterrupt()
            return {'state': 'missing', 'source': choices[0]}
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            target = Path(root) / 'partial'
            with self.assertRaises(KeyboardInterrupt):
                scan(self.project(), target, query, object())
            body = json.loads((target / 'inventory.json').read_text(encoding='utf-8'))
            self.assertEqual(len(body['records']), 2)
            self.assertFalse(body['finished'])

    def test_failed_auth_does_not_save_or_echo_secret(self):
        secret = 'fake-secret-never-real'
        request = json.dumps({'action': 'connect-account', 'options': {'key': 'fake-key', 'secret': secret}})
        output = io.StringIO()
        with patch('sys.stdin', io.StringIO(request)), contextlib.redirect_stdout(output), \
             patch('ges.eumetsat_auth.authenticated_token', side_effect=RuntimeError(secret)), \
             patch('ges.eumetsat_auth.save_credentials') as save:
            with self.assertRaises(SystemExit):
                main()
            save.assert_not_called()
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['type'], 'error')

    def test_authentication_precedes_encrypted_save(self):
        output, order = io.StringIO(), []
        request = json.dumps({'action': 'connect-account', 'options': {'key': 'fake', 'secret': 'fake-secret'}})
        with patch('sys.stdin', io.StringIO(request)), contextlib.redirect_stdout(output), \
             patch('ges.eumetsat_auth.authenticated_token', side_effect=lambda _: order.append('auth')), \
             patch('ges.eumetsat_auth.save_credentials', side_effect=lambda *_: order.append('save')):
            main()
        self.assertEqual(order, ['auth', 'save'])
        self.assertTrue(json.loads(output.getvalue())['configured'])
