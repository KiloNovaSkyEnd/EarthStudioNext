"""Persistent per-frame retries; never approves or completes a failed frame."""
import json,time
from datetime import datetime,timezone
from pathlib import Path
from ges_next.production.assets import write_json

SHORT_DELAY=30
MAX_DELAY=300
REVIEW_DELAY=1800

def enabled(root):
    path=Path(root)/'unattended.json'
    return path.is_file() and json.loads(path.read_text(encoding='utf-8')).get('enabled') is True

class RetryBook:
    def __init__(self,root,known,active=True):
        self.root=Path(root);self.active=active;self.rows={};self.known=set(known)
        path=self.root/'frame_retries.json'
        if active and path.exists():
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('schema')!='earthstudio.frame_retries.v1':raise ValueError('Unknown retry state; preserve original files')
            for utc,row in data['frames'].items():
                if utc not in self.known or row.get('utc')!=utc:raise ValueError('Retry state does not belong to this frozen plan')
                if type(row.get('attempt')) is not int or row['attempt']<1 or type(row.get('next_unix')) not in (int,float):raise ValueError('Invalid retry counter/time')
                self.rows[utc]=row
    def persist(self):
        write_json(self.root/'frame_retries.json',dict(schema='earthstudio.frame_retries.v1',updated_utc=datetime.now(timezone.utc).isoformat(),frames=self.rows))
    def defer(self,step,failure,downloading,now=None):
        now=time.time() if now is None else now;utc=step['utc']
        if utc not in self.known:raise ValueError('Cannot retry a frame outside this plan')
        attempt=self.rows.get(utc,{}).get('attempt',0)+1
        # Identity/quality/schema errors remain visible and receive a slow recheck.
        # No committed outputs or inputs are removed or replaced by this scheduler.
        review=failure['error_type'] in ('ValueError','FileNotFoundError','KeyError') or attempt>5
        delay=REVIEW_DELAY if review else min(MAX_DELAY,SHORT_DELAY*2**min(attempt-1,4))
        row=dict(utc=utc,attempt=attempt,next_unix=now+delay,retry_seconds=delay,requires_attention=review,downloading=bool(downloading),**{k:failure.get(k) for k in ('stage','error_type','error','traceback')})
        self.rows[utc]=row;self.persist();return self.describe(utc)
    def describe(self,utc):
        row=self.rows[utc]
        return dict(utc=utc,phase='retry-wait',retry=dict(attempt=row['attempt'],retry_seconds=max(0,int(row['next_unix']-time.time())),requires_attention=row['requires_attention'],stage=row['stage'],error=row['error']))
    def due(self,now=None):
        now=time.time() if now is None else now
        return [utc for utc,row in sorted(self.rows.items(),key=lambda item:item[1]['next_unix']) if row['next_unix']<=now]
    def complete(self,utc):
        if utc in self.rows:del self.rows[utc];self.persist()
