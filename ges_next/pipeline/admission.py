"""Bound simultaneous scans instead of multiplying all per-process resource limits."""
import json,os,shutil
from pathlib import Path

GIB=1024**3
MAX_SCANS=8


def options(root):
    file=Path(root)/'execution.json'
    value=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    if value.get('mode','serial') not in ('serial','parallel'):raise ValueError('Unknown execution mode')
    if value.get('control','auto') not in ('auto','manual'):raise ValueError('Unknown concurrency control')
    for key in ('max_compute','prefetch'):
        if type(value.get(key,2)) is not int or not 1<=value.get(key,2)<=MAX_SCANS:raise ValueError('并发及预取上限必须为1–8')
    cap=value.get('recommended_max_compute',MAX_SCANS)
    if type(cap) is not int or not 1<=cap<=MAX_SCANS:raise ValueError('Invalid measured concurrency recommendation')
    for key in ('compute_threads','decode_threads'):
        if type(value.get(key,0)) is not int or not 0<=value.get(key,0)<=8:raise ValueError('线程数必须为0（自动）或1–8')
    profiles=value.get('thread_profiles',{})
    if not isinstance(profiles,dict) or any(not str(k).isdigit() or not 1<=int(k)<=MAX_SCANS or
        type(v) is not int or not 1<=v<=8 for k,v in profiles.items()):raise ValueError('Invalid measured thread profiles')
    return value


def capacity(root,plan,requested=3,available=None):
    if available is None:
        import psutil
        available=psutil.virtual_memory().available
    # Initial estimate; live admission includes measured peaks and unallocated worker reservations.
    memory=max(1,int((available-4*GIB)//(6*GIB)))
    disk=max(0,int((shutil.disk_usage(root).free-plan['largest_scan_bytes']*MAX_SCANS)//plan['minimum_start_free_bytes']))
    return max(0,min(requested,MAX_SCANS,memory,disk,max(1,(os.cpu_count() or 2)//2)))


def can_start(packages,available=None,budget=6*GIB,reserve=6*GIB):
    if available is None:
        import psutil
        available=psutil.virtual_memory().available
    outstanding=0
    for package in packages:
        file=Path(package)/'scratch/work/reports/resource_usage.json'
        try:rss=json.loads(file.read_text(encoding='utf-8'))['process_rss_bytes']
        except (OSError,ValueError,KeyError):rss=0
        outstanding+=max(0,budget-rss)
    return available>=budget+reserve+outstanding
