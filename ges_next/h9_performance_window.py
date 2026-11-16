"""Expiring, exact-scan experiment window before any science process starts."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import time


def wait_for_window(project,utc,generation,*,clock=None,sleep=None,report=None):
    clock=clock or (lambda:datetime.now(timezone.utc))
    sleep=sleep or time.sleep
    project=Path(project)
    control=project/'reports/performance_window.json'
    began=clock()
    while control.exists():
        state=json.loads(control.read_text(encoding='utf-8'))
        if state.get('state')!='hold' or state.get('utc')!=utc:return
        created=datetime.fromisoformat(state['created_utc'])
        expires=datetime.fromisoformat(state['expires_utc'])
        if (created.utcoffset() is None or expires.utcoffset() is None
                or not 0<(expires-created).total_seconds()<=1200):
            raise ValueError('Performance window must expire within20 minutes')
        now=clock()
        if now>=expires or (now-began).total_seconds()>=1200:return
        scope=project/'requested_scope.json'
        if scope.exists() and json.loads(scope.read_text(encoding='utf-8'))['generation']>generation:
            raise SystemExit(75)
        if report:report(dict(state='waiting',utc=utc,token=state['token'],pid=os.getpid(),
            updated_utc=now.isoformat(),expires_utc=expires.isoformat()))
        sleep(2)
