import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ges.native_bridge import scan
from ges_next.catalog_cache import CatalogCache
from ges_next.inventory_selection import groups
from ges_next.selection import utc


class CatalogCacheTests(unittest.TestCase):
    def project(self, start=0, end=20, satellites=None):
        return dict(Id='cache-test', StartUtc=f'2026-10-20T13:{start:02}:00Z',
                    EndUtc=f'2026-10-20T13:{end:02}:00Z', IntervalMinutes=10,
                    SatelliteSelection=dict(Mode='manual', Satellites=satellites or ['himawari9']))

    def test_overlap_new_satellite_reopen_and_fresh_inventory_accounting(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            calls=[]
            def query(when, choices, client):
                calls.append((when, choices))
                return dict(source=choices[0], bytes=20, native=dict(keys=[choices[0]+str(when)]))
            cache=CatalogCache(Path(folder)/'cache')
            def run(project, name):
                return json.loads(Path(scan(project, Path(folder)/name,
                    query_fn=lambda w,c,client:cache.query(w,c,client,query), client=object(),
                    groups_fn=lambda w:groups(project,w))).read_text(encoding='utf-8'))
            first=run(self.project(), 'first')
            cache.close();cache=CatalogCache(Path(folder)/'cache')
            second=run(self.project(10,30), 'second')
            self.assertEqual(len(calls),4)  # 3 initial + only the new13:30 node
            self.assertEqual([r['cache_hit'] for r in second['records']], [True,True,False])
            self.assertEqual(second['known_unique_bytes'],60)
            self.assertTrue(second['finished'])
            run(self.project(10,30,['himawari9','goes19']), 'multisat')
            self.assertEqual(len(calls),7)  # Only the newly selected satellite.
            self.assertFalse(first['records'][0]['cache_hit'])
            cache.close()

    def test_failed_queries_retry_missing_reuse_and_explicit_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=CatalogCache(folder);when=utc('2026-10-20T13:00Z');calls=[]
            def fake(*args):calls.append(1);return dict(state='unavailable',source='himawari9')
            for _ in range(2):cache.query(when,['himawari9'],None,fake)
            self.assertEqual(len(calls),2)
            cache.save(when,['himawari9'],dict(state='missing',source='himawari9'))
            self.assertTrue(cache.query(when,['himawari9'],None,fake)['cache_hit'])
            cache.query(when,['himawari9'],None,fake,refresh=True)
            cache.query(when,['himawari9'],None,fake)
            self.assertEqual(len(calls),4);cache.close()

    def test_contract_and_ordered_fallbacks_do_not_cross_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=CatalogCache(folder);when=utc('2026-10-20T13:00Z')
            cache.save(when,['goes19','goes16'],dict(state='missing'))
            def fake(*args):return dict(state='missing')
            self.assertFalse(cache.query(when,['goes16','goes19'],None,fake)['cache_hit'])
            cache.version='changed-band-contract'
            self.assertFalse(cache.query(when,['goes19','goes16'],None,fake)['cache_hit']);cache.close()

    def test_partial_old_inventory_adopted_without_modifying_source(self):
        from ges_next.noaa import AHI_BANDS
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'projects/p/inventories/old/inventory.json';path.parent.mkdir(parents=True)
            project=self.project();when=utc(project['StartUtc']);region=groups(project,when)[0][0]
            body=dict(satellite_selection=project['SatelliteSelection'],finished=False,records=[dict(source='himawari9',state='available',
                requested_utc=when.isoformat(),region=region,native=dict(bands=list(AHI_BANDS),complete=True,keys=['real-catalog-key']))])
            original=json.dumps(body).encode();path.write_bytes(original)
            cache=CatalogCache(root/'cache');cache.import_inventories(root/'projects')
            def forbidden(*args):self.fail('Old completed query was repeated')
            self.assertTrue(cache.query(when,['himawari9'],None,forbidden)['cache_hit'])
            self.assertEqual(path.read_bytes(),original);cache.close()

    def test_interruption_after_cache_commit_needs_no_query_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            when=utc('2026-10-20T13:00Z');cache=CatalogCache(folder)
            cache.query(when,['himawari9'],None,lambda *args:dict(state='missing'));cache.close()
            cache=CatalogCache(folder)
            self.assertTrue(cache.query(when,['himawari9'],None,lambda *args:self.fail('Repeated'))['cache_hit']);cache.close()

    def test_shrinking_range_reuses_completed_records_without_discarding_outer_cache(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            cache=CatalogCache(Path(folder)/'cache');calls=[]
            def query(when,choices,client):
                calls.append(when);return dict(source=choices[0],native=dict(keys=[str(when)]),bytes=1)
            # An interrupted wider request has already committed the first three nodes.
            for minute in (0,10,20):cache.query(utc(f'2026-10-20T13:{minute:02}:00Z'),['himawari9'],None,query)
            def run(project,name):
                return json.loads(Path(scan(project,Path(folder)/name,
                    query_fn=lambda w,c,client:cache.query(w,c,client,query),client=object(),
                    groups_fn=lambda w:groups(project,w))).read_text(encoding='utf-8'))
            short=run(self.project(10,20),'smaller')
            self.assertEqual(len(calls),3)
            self.assertEqual(len(short['records']),2)
            self.assertTrue(all(r['cache_hit'] for r in short['records']))
            self.assertTrue(short['finished'])
            again=run(self.project(0,30),'expanded_again')
            self.assertEqual(len(calls),4)  # Outer13:00 kept; only13:30 is new.
            self.assertEqual(len(again['records']),4);cache.close()


if __name__=='__main__':unittest.main()
