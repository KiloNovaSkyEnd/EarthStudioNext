"""Request a safe existing-queue handoff; never terminate active science work."""
import json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ges_next.production.assets import write_json
from ges_next.pipeline.runner import load

root,plan,state=load(Path(sys.argv[1]))
if state['phase']!='parallel-running':raise ValueError('Expected an active parallel queue')
before=json.loads((root/'execution.json').read_text(encoding='utf-8'))
value=dict(mode='parallel',control='auto',max_compute=8,prefetch=3)
write_json(root/'execution.json',value)
stamp=datetime.now(timezone.utc).isoformat()
write_json(root/'pause_requested.json',dict(requested_utc=stamp,reason='adaptive_scheduler_safe_handoff'))
write_json(ROOT/'reports/m7_performance/adaptive_handoff.json',dict(requested_utc=stamp,
    queue=str(root),before=before,execution=value,completed_before=len(state['completed']),
    active_before=state.get('active'),status='safe_pause_requested'))
print('Safe pause requested; started scans must finish before resume.')
