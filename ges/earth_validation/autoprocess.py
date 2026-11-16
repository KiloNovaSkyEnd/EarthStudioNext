"""Archive checks and the current processing entry; no legacy material imports."""
import json
from pathlib import Path
from .archive import target_for


def audit_archive(root,plan):
    problems=[]
    for row in plan['records']:
        path=target_for(root,row); receipt=path.with_suffix(path.suffix+'.receipt.json')
        if not path.is_file() or path.stat().st_size!=row['size'] or not receipt.is_file():
            problems.append(str(path)); continue
        info=json.loads(receipt.read_text(encoding='utf-8'))
        if info.get('size')!=row['size'] or info.get('etag')!=row.get('etag') or len(info.get('sha256',''))!=64:
            problems.append(str(path))
    return problems


def run(root,download_pid,blender):
    # The legacy material was frozen. Only a committed complete archive can
    # enter the current pilot, regardless of the old downloader's PID.
    plan=json.loads((Path(root)/'inventory.json').read_text(encoding='utf-8'))
    if audit_archive(root,plan): raise RuntimeError('Archive incomplete; do not start processing')
    from .stock_job import run as stock_pilot
    stock_pilot(root)
    from .stock_export import export
    export(root,blender)
