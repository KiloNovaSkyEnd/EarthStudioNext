"""Read-only production timing/telemetry audit; writes only its own report."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ges_next.isolation import require_writable
import psutil


def audit(project, sample_seconds=10):
    frames = []
    for path in sorted((project / 'processed').glob('*/native_master.json')):
        master = json.loads(path.read_text(encoding='utf-8'))
        rows = defaultdict(float)
        planning = compute = kernel = transfer = 0.0
        calls = 0
        for tile in master['tiles']:
            phase = tile.get('phaseSeconds', {})
            planning += phase.get('planning', 0)
            compute += phase.get('compute_and_write', 0)
            rows[tile['path'].split('_')[1]] += sum(phase.values())
            calls += tile.get('execution', {}).get('gpu_calls', 0)
        # GPU counters in receipts are cumulative within each row process.
        # Select its final tile, never sum cumulative counters over four tiles.
        for row in rows:
            tiles = [t for t in master['tiles'] if t['path'].split('_')[1] == row]
            last = max(tiles, key=lambda t: t['path'])
            telemetry = last.get('execution', {}).get('gpu_telemetry', {})
            kernel += telemetry.get('total_kernel_ms', 0) / 1000
            transfer += telemetry.get('total_transfer_and_compute_seconds', 0)
        frames.append(dict(utc=master['utc'], seconds=master['runSeconds'],
            mode=master.get('runMode', 'legacy-unlabelled'),
            backend='cuda-night' if calls else 'cpu', gpu_calls=calls,
            tile_planning_sum_seconds=planning, tile_compute_write_sum_seconds=compute,
            row_seconds=dict(rows), gpu_kernel_sum_seconds=kernel,
            gpu_transfer_compute_sum_seconds=transfer,
            tile_bytes=sum((path.parent / t['path']).stat().st_size for t in master['tiles'])))
    processes = []
    for p in psutil.process_iter(['pid', 'cmdline', 'name']):
        try:
            cmd = p.info['cmdline'] or []
            if not any('prepare_native_h9_disk.py' in s for s in cmd) or '--row' not in cmd:
                continue
            # Ignore Windows venv launchers: actual interpreters own the CPU time.
            if p.memory_info().rss < 50 * 1024**2:
                continue
            cpu = p.cpu_times()
            processes.append((p, cpu.user + cpu.system, p.io_counters()))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    began = time.monotonic()
    time.sleep(sample_seconds)
    elapsed = time.monotonic() - began
    samples = []
    for p, before, io in processes:
        try:
            cpu = p.cpu_times(); after_io = p.io_counters()
            samples.append(dict(pid=p.pid, effective_cpu_cores=(cpu.user+cpu.system-before)/elapsed,
                rss_bytes=p.memory_info().rss,
                read_bytes_delta=after_io.read_bytes-io.read_bytes,
                write_bytes_delta=after_io.write_bytes-io.write_bytes))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            samples.append(dict(pid=p.pid, exited_during_sample=True))
    groups = {}
    for mode, backend in sorted({(f['mode'], f['backend']) for f in frames}):
        values = [f['seconds'] for f in frames if (f['mode'], f['backend']) == (mode, backend)]
        groups[f'{mode}/{backend}'] = dict(count=len(values), median_seconds=statistics.median(values),
            min_seconds=min(values), max_seconds=max(values))
    # A restart revalidates committed masters. Never pair an old compute start
    # with a later process's validation-only commit for the same UTC.
    stages = defaultdict(dict)
    for logfile in sorted((project/'reports').glob('processing*.stdout.log')):
        for line in logfile.read_text(encoding='utf-8', errors='replace').splitlines():
            if not line.startswith('{'): continue
            try: event = json.loads(line)
            except ValueError: continue
            if event.get('utc') and event.get('stage') and event.get('updated_utc'):
                stages[(logfile.name,event['utc'])][event['stage']] = event['updated_utc']
    coordinator = []
    for (logfile,utc), stage in sorted(stages.items()):
        names = ['downloading_H9_scan','decoding_H9_scan','composing_native_H9','native_frame_committed']
        if not all(n in stage for n in names): continue
        times = [datetime.fromisoformat(stage[n]) for n in names]
        if any(b<a for a,b in zip(times,times[1:])): continue
        coordinator.append(dict(logfile=logfile,utc=utc, download_verify_seconds=(times[1]-times[0]).total_seconds(),
            decode_seconds=(times[2]-times[1]).total_seconds(),
            compute_validate_seconds=(times[3]-times[2]).total_seconds(),
            total_seconds=(times[3]-times[0]).total_seconds()))
    return dict(created_utc=datetime.now(timezone.utc).isoformat(), frames=frames, groups=groups,
        coordinator_stages=coordinator,
        live=dict(sample_seconds=elapsed, processes=samples, logical_cpus=psutil.cpu_count(),
            physical_available_bytes=psutil.virtual_memory().available),
        limits='Read-only snapshots during active production. Different UTCs are not controlled speed tests. '
               'Row times sum measured planning/compute only; exclude startup/hash/GC. GPU event times exclude CPU work; '
               'transfer counters include host overhead and sync. Process I/O includes cached I/O. No pixel reread/parity test here.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = require_writable(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = audit(args.project)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(groups=report['groups'], live=report['live'], latest=report['frames'][-3:]), indent=2))
