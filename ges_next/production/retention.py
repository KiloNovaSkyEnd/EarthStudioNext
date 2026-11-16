"""Two-phase precise cleanup; only new job-owned, unshared, verified input files."""
import json
import os
from pathlib import Path
from .owned_files import owned_path, snapshot, delete_verified


class Retention:
    def __init__(self,journal): self.journal=journal

    def _recover_absent_intents(self,job,utc):
        value=self.journal.job(job); path=Path(value['root'])/'cleanup_intents.jsonl'
        if not path.exists(): return
        for line in path.read_text(encoding='utf-8').splitlines():
            try: intent=json.loads(line)
            except json.JSONDecodeError: continue  # A crash can leave an incomplete final log line.
            if intent.get('job')!=job or intent.get('utc')!=utc: continue
            row=self.journal.db.execute('SELECT * FROM sources WHERE id=?',(intent['id'],)).fetchone()
            if row and row['owner']==job and not row['deleted'] and json.loads(row['stamp'])==intent['stamp'] and row['path']==intent['path']:
                owned_path(value['root'],row['path'],row['role'])
                if not Path(row['path']).exists():
                    self.journal.db.execute('UPDATE sources SET deleted=1 WHERE id=?',(row['id'],))
                    self.journal.db.execute('INSERT INTO events(job,utc,action,data) VALUES(?,?,?,?)',(job,utc,'recovered-absent-after-intent',line))

    def plan(self,job,utc):
        step=self.journal.gate(job,utc)
        self._recover_absent_intents(job,utc)
        value=self.journal.job(job); candidates=[]; retained=[]
        rows=self.journal.db.execute('SELECT s.* FROM sources s JOIN claims c ON s.id=c.source WHERE c.job=? AND c.utc=? AND s.deleted=0',(job,utc)).fetchall()
        for row in rows:
            reason=None
            if row['owner']!=job or row['role']=='reused': reason='read-only/shared historical source'
            elif value['keep_l1'] and row['role']=='l1': reason='keepL1 selected'
            elif value['keep_temp'] and row['role']=='temporary': reason='keepIntermediates selected'
            else:
                claimed=self.journal.db.execute('SELECT job,utc FROM claims WHERE source=? AND released=0 AND NOT(job=? AND utc=?)',(row['id'],job,utc)).fetchall()
                if claimed: reason='still referenced by another unfinished/unaccepted step'
            if reason:
                retained.append(dict(path=row['path'],reason=reason));continue
            owned_path(value['root'],row['path'],row['role'])
            expected=json.loads(row['stamp'])
            if expected['links']!=1: retained.append(dict(path=row['path'],reason='hardlinked/shared file'));continue
            if snapshot(row['path'])!=expected: raise ValueError('Input changed; no cleanup: '+row['path'])
            # Recheck every previously released dependent step, not only this job.
            for claim in self.journal.db.execute('SELECT job,utc FROM claims WHERE source=? AND released=1',(row['id'],)).fetchall():
                self.journal.gate(claim['job'],claim['utc'])
            candidates.append(dict(id=row['id'],path=row['path'],role=row['role'],stamp=expected))
        return dict(schema='earthstudio.cleanup_plan.v1',job=job,utc=utc,manifest_sha256=step['hash'],candidates=candidates,retained=retained)

    def execute(self,plan):
        job,utc=plan['job'],plan['utc'];db=self.journal.db
        db.execute('BEGIN IMMEDIATE')
        deleted=[]
        try:
            current=self.plan(job,utc)
            if current!=plan: raise ValueError('Cleanup plan became stale; review/rebuild it')
            root=Path(self.journal.job(job)['root'])
            with (root/'cleanup_intents.jsonl').open('a',encoding='utf-8') as log:
                for offset in range(0,len(current['candidates']),16):
                    group=current['candidates'][offset:offset+16]
                    for item in group:
                        owned_path(root,item['path'],item['role'])
                        log.write(json.dumps(dict(job=job,utc=utc,**item),ensure_ascii=False)+'\n')
                    # Every deletion in this group has a durable intent first.
                    # Recovery already distinguishes absent from present files.
                    log.flush();os.fsync(log.fileno())
                    for item in group:
                        owned_path(root,item['path'],item['role'])
                        delete_verified(item['path'],item['stamp'])
                        db.execute('UPDATE sources SET deleted=1 WHERE id=?',(item['id'],))
                        db.execute('INSERT INTO events(job,utc,action,data) VALUES(?,?,?,?)',
                            (job,utc,'deleted-owned-input',json.dumps(dict(job=job,utc=utc,**item))))
                        deleted.append(item)
            db.execute('UPDATE claims SET released=1 WHERE job=? AND utc=?',(job,utc))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        return dict(deleted_files=len(deleted),deleted_logical_bytes=sum(i['stamp']['bytes'] for i in deleted),
                    retained=current['retained'],actual_free_space_not_inferred_from_logical_bytes=True)
