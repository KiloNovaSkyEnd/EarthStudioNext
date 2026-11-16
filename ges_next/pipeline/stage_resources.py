"""Stage-aware reservations; a finished science PID is never treated as live memory."""
import json
from pathlib import Path
import psutil
from .admission import GIB


def tree_rss(pid,created=None):
    try:
        process=psutil.Process(pid)
        if created is not None and abs(process.create_time()-created)>.01:return 0
        total=process.memory_info().rss
        for child in process.children(recursive=True):
            try:total+=child.memory_info().rss
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        return total
    except (psutil.NoSuchProcess,psutil.AccessDenied):return 0


def package_phase(task):
    return (Path(task['package']),task['phase']) if isinstance(task,dict) else (Path(task),'producing')


def live_rss(package,role):
    receipt=Path(package)/(role+'_worker.process.json')
    try:
        value=json.loads(receipt.read_text(encoding='utf-8'))
        if value['created'] is None:return 0
        return tree_rss(value['pid'],value['created'])
    except (OSError,ValueError,KeyError):return 0


def can_start_science(tasks,budget,verification_budget,available=None,reserve=4*GIB):
    if available is None:available=psutil.virtual_memory().available
    outstanding=0;verification=False;verification_rss=0
    for task in tasks:
        package,phase=package_phase(task)
        if phase=='producing':
            task_budget=task.get('budget_bytes',budget) if isinstance(task,dict) else budget
            outstanding+=max(0,task_budget-live_rss(package,'science'))
        elif phase in ('waiting-verification','verifying'):
            verification=True;verification_rss+=live_rss(package,'verification')
        elif phase=='verifying-assets':
            # H9 11K one-at-a-time full JPEG/mask decode in the coordinator;
            # do not reserve a nonexistent Blender subprocess tree.
            outstanding+=2*GIB
        # Cleaning has no science arrays/Blender child; retain the global OS reserve.
    if verification:outstanding+=max(0,verification_budget-verification_rss)
    return available>=reserve+budget+outstanding
