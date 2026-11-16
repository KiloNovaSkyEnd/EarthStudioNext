import tempfile,threading,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from ges_next.production.journal import Journal
from ges_next.production.profile import h9_profile


class ConcurrentRegistrationTests(unittest.TestCase):
    def test_simultaneous_shared_input_registration_keeps_one_identity_and_all_claims(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()/'reports') as folder:
            root=Path(folder);database=root/'journal.sqlite';source=root/'shared.bin';source.write_bytes(b'read-only source')
            journal=Journal(database)
            try:jobs=[journal.create_job(root/f'job{i}',h9_profile(95,1000)) for i in range(4)]
            finally:journal.close()
            barrier=threading.Barrier(4)
            class Proxy:
                def __init__(self,connection):self.connection=connection;self.first=True
                def execute(self,sql,*args):
                    cursor=self.connection.execute(sql,*args)
                    if self.first and sql.startswith('SELECT * FROM sources WHERE path='):
                        self.first=False;barrier.wait(timeout=10)
                    return cursor
                def __getattr__(self,name):return getattr(self.connection,name)
            def register(job):
                item=Journal(database);item.db=Proxy(item.db)
                try:return item.register_input(job,'2026-10-12T03:50:00Z',source,'reused')
                finally:item.close()
            with ThreadPoolExecutor(max_workers=4) as pool:identities=list(pool.map(register,jobs))
            self.assertEqual(len(set(identities)),1)
            journal=Journal(database)
            try:
                self.assertEqual(journal.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0],1)
                self.assertEqual(journal.db.execute('SELECT COUNT(*) FROM claims').fetchone()[0],4)
                self.assertIsNone(journal.db.execute('SELECT owner FROM sources').fetchone()[0])
            finally:journal.close()


if __name__=='__main__':unittest.main()
