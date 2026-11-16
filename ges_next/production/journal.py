"""Persistent job ownership, shared source claims, commits and verification gates."""
import json
from pathlib import Path
import sqlite3
import uuid
from .assets import digest, write_json, verify_assets
from .owned_files import snapshot, owned_path


class Journal:
    def __init__(self, path):
        from ges_next.isolation import require_writable
        path = require_writable(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None,timeout=120)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA foreign_keys=ON;
          PRAGMA journal_mode=WAL;
          PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, root TEXT UNIQUE, profile TEXT, keep_l1 INTEGER, keep_temp INTEGER, owned INTEGER, approved INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS steps(job TEXT REFERENCES jobs(id), utc TEXT, manifest TEXT, hash TEXT, evidence TEXT, evidence_hash TEXT, state TEXT, PRIMARY KEY(job,utc));
          CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, path TEXT UNIQUE, owner TEXT REFERENCES jobs(id), role TEXT, stamp TEXT, deleted INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS claims(job TEXT REFERENCES jobs(id), utc TEXT, source INTEGER REFERENCES sources(id), released INTEGER DEFAULT 0, PRIMARY KEY(job,utc,source));
          CREATE INDEX IF NOT EXISTS claims_by_source_release ON claims(source,released,job,utc);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job TEXT, utc TEXT, action TEXT, data TEXT);
        ''')

    def close(self): self.db.close()

    def create_job(self, root, profile, keep_l1=False, keep_intermediates=False, existing_readonly=False):
        from ges_next.isolation import require_writable
        root = require_writable(root)
        row = self.db.execute('SELECT * FROM jobs WHERE root=?',(str(root),)).fetchone()
        serialized = json.dumps(profile,sort_keys=True)
        if row:
            if row['profile'] != serialized: raise ValueError('Existing job profile is immutable')
            if bool(row['keep_l1'])!=bool(keep_l1) or bool(row['keep_temp'])!=bool(keep_intermediates):
                raise ValueError('Retention options differ from existing job')
            return row['id']
        if root.exists() and any(root.iterdir()) and not existing_readonly:
            raise ValueError('Cannot adopt pre-existing files as job-owned cleanup inputs')
        root.mkdir(parents=True,exist_ok=True)
        job = uuid.uuid4().hex
        self.db.execute('INSERT INTO jobs(id,root,profile,keep_l1,keep_temp,owned) VALUES(?,?,?,?,?,?)',
                        (job,str(root),serialized,int(keep_l1),int(keep_intermediates),int(not existing_readonly)))
        write_json(root/'production_owner.json',dict(job=job,owned_inputs_allowed=not existing_readonly))
        return job

    def job(self, job):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        if row is None: raise ValueError('Unknown production job')
        return dict(row)

    def register_input(self, job, utc, path, role):
        prepared=self._prepare_input(self.job(job),path,role)
        return self._register_prepared(job,utc,*prepared)

    def _prepare_input(self,value,path,role):
        if role not in ('l1','temporary','reused'): raise ValueError('Unknown input role')
        from ges_next.path_identity import normal_namespace
        path = Path(normal_namespace(Path(path).absolute()))
        if role != 'reused':
            if not value['owned']: raise ValueError('Existing job inputs are read-only')
            owned_path(value['root'],path,role)
        stamp = snapshot(path)
        return path,role,stamp

    def _register_prepared(self,job,utc,path,role,stamp):
        old = self.db.execute('SELECT * FROM sources WHERE path=?',(str(path),)).fetchone()
        if old is None:
            # Multiple jobs may register the same read-only cached source concurrently.
            # Preserve the first identity/owner; never overwrite on a path conflict.
            self.db.execute('INSERT INTO sources(path,owner,role,stamp) VALUES(?,?,?,?) ON CONFLICT(path) DO NOTHING',
                (str(path),None if role=='reused' else job,role,json.dumps(stamp,sort_keys=True)))
            old=self.db.execute('SELECT * FROM sources WHERE path=?',(str(path),)).fetchone()
        if old is None or old['stamp'] != json.dumps(stamp,sort_keys=True) or old['deleted']:
            raise ValueError('Registered input identity changed')
        source = old['id']
        self.claim(job,utc,source)
        return source

    def register_inputs(self,job,utc,entries):
        # Hash outside the short write transaction; retain the exact same
        # identity/owner conflict checks and final protected deletion checks.
        value=self.job(job)
        prepared=[self._prepare_input(value,path,role) for path,role in entries]
        if self.db.in_transaction:raise ValueError('Input registration requires its own transaction')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result=[self._register_prepared(job,utc,*entry) for entry in prepared]
            self.db.execute('COMMIT');return result
        except BaseException:self.db.execute('ROLLBACK');raise

    def claim(self, job, utc, source):
        self.job(job)
        row=self.db.execute('SELECT deleted,path FROM sources WHERE id=?',(source,)).fetchone()
        if row is None or row['deleted'] or not Path(row['path']).is_file(): raise ValueError('Input unavailable/already reclaimed')
        self.db.execute('INSERT OR IGNORE INTO claims(job,utc,source) VALUES(?,?,?)',(job,utc,source))

    def submit(self, job, utc, manifest):
        from ges_next.path_identity import canonical
        value = self.job(job); manifest=canonical(manifest)
        if not manifest.is_relative_to(Path(value['root'])): raise ValueError('Commit outside job')
        data=json.loads(manifest.read_text(encoding='utf-8'))
        verify_assets(manifest.parent,data['assets'])
        if data['utc'] != utc: raise ValueError('Commit time differs')
        if self.db.execute('SELECT 1 FROM steps WHERE job=? AND utc=?',(job,utc)).fetchone(): raise ValueError('Step already committed')
        self.db.execute('INSERT INTO steps(job,utc,manifest,hash,state) VALUES(?,?,?,?,?)',(job,utc,str(manifest),digest(manifest),'committed'))

    def verify(self, job, utc, evidence):
        from .verification import validate_reopen
        row = self.step(job,utc)
        from ges_next.path_identity import canonical
        evidence=canonical(evidence)
        validate_reopen(self.job(job),row,evidence)
        self.db.execute('UPDATE steps SET evidence=?,evidence_hash=?,state=? WHERE job=? AND utc=?',
                        (str(evidence),digest(evidence),'verified',job,utc))

    def approve_profile(self, job, *, user_quality_accepted):
        if user_quality_accepted is not True: raise ValueError('User quality acceptance required for new profile')
        if not self.db.execute("SELECT 1 FROM steps WHERE job=? AND state='verified'",(job,)).fetchone():
            raise ValueError('Independent reopen must pass first')
        self.db.execute('UPDATE jobs SET approved=1 WHERE id=?',(job,))

    def step(self, job, utc):
        row=self.db.execute('SELECT * FROM steps WHERE job=? AND utc=?',(job,utc)).fetchone()
        if row is None: raise ValueError('No committed step')
        return dict(row)

    def gate(self, job, utc):
        from .verification import validate_reopen
        value=self.job(job); row=self.step(job,utc)
        if not value['approved'] or row['state'] != 'verified': raise ValueError('Quality/reopen gate not passed')
        if digest(row['evidence']) != row['evidence_hash']: raise ValueError('Reopen evidence changed')
        # The fresh verify pass decoded these exact asset bytes. Every gate still
        # rehashes all assets/evidence/scene; unchanged bytes need no repeat decode.
        validate_reopen(value,row,Path(row['evidence']),decode_images=False,enforce_current_contract=False)
        return row

    def release_claims(self, job, utc):
        self.gate(job,utc)
        self.db.execute('UPDATE claims SET released=1 WHERE job=? AND utc=?',(job,utc))
