import tempfile,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from ges_next.production.journal import Journal
from ges_next.production.profile import h9_profile


class BulkRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd()/'reports');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'journal.sqlite'
        self.j=Journal(self.db);self.addCleanup(self.j.close)
        self.job=self.j.create_job(self.root/'job',h9_profile(95,1000))
        self.paths=[]
        for i in range(3):
            p=self.root/f'shared{i}.bin';p.write_bytes(bytes([i])*20);self.paths.append(p)

    def test_batch_keeps_full_sync_and_one_atomic_commit(self):
        trace=[];self.j.db.set_trace_callback(trace.append)
        ids=self.j.register_inputs(self.job,'fixture',[(p,'reused') for p in self.paths])
        self.assertEqual(len(ids),3);self.assertEqual(trace.count('BEGIN IMMEDIATE'),1);self.assertEqual(trace.count('COMMIT'),1)
        self.assertEqual(self.j.db.execute('PRAGMA synchronous').fetchone()[0],2)

    def test_identity_conflict_rolls_back_all_new_registrations(self):
        old=self.paths[1];self.j.register_input(self.job,'old',old,'reused');old.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.j.register_inputs(self.job,'new',[(self.paths[0],'reused'),(old,'reused')])
        self.assertEqual(self.j.db.execute('SELECT count(*) FROM sources').fetchone()[0],1)
        self.assertEqual(self.j.db.execute('SELECT count(*) FROM claims WHERE utc=?',('new',)).fetchone()[0],0)

    def test_concurrent_batches_preserve_shared_owner_and_every_claim(self):
        jobs=[self.j.create_job(self.root/f'job{i}',h9_profile(95,1000)) for i in range(4)]
        def run(job):
            journal=Journal(self.db)
            try:return journal.register_inputs(job,'fixture',[(p,'reused') for p in self.paths])
            finally:journal.close()
        with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(run,jobs))
        self.assertTrue(all(row==rows[0] for row in rows))
        self.assertEqual(self.j.db.execute('SELECT count(*) FROM claims').fetchone()[0],12)
        self.assertEqual(self.j.db.execute('SELECT count(*) FROM sources WHERE owner IS NOT NULL').fetchone()[0],0)
