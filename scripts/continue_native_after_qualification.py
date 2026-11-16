"""Hand the successful full-disk qualification to the standalone native engine.

No scientific recipe changes, blind retries, proxy stages, or deletions. The
engine owns its existing project lock and all later scientific/render gates.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import psutil


def main(root, engine, blender, wait_pid, label='v20'):
    if not label.isidentifier():
        raise ValueError('Invalid log label')
    root, engine, blender = map(lambda p: Path(p).resolve(), (root, engine, blender))
    reports = root / 'reports'
    report = reports / f'native_handoff_{label}.json'

    def status(state, **extra):
        value = dict(state=state, updated_utc=datetime.now(timezone.utc).isoformat(),
                     engine=str(engine), global_delivery_complete=False, **extra)
        # Separate report owned by this supervisor; science does not depend on it.
        try:
            report.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass
        print(json.dumps(value, ensure_ascii=False), flush=True)

    if not engine.is_file() or not blender.is_file():
        raise FileNotFoundError('Standalone engine and Blender are required')
    qualification_started = None
    try:
        waiting = psutil.Process(wait_pid)
        qualification_started = waiting.create_time()
        command = waiting.cmdline()
        if not any('qualify_full_native_memory.py' in part for part in command):
            raise ValueError('Refusing to wait on an unrelated process')
        status('waiting_for_full_native_qualification', qualification_pid=wait_pid)
        waiting.wait()
    except psutil.NoSuchProcess:
        pass
    receipt = reports / 'full_native_memory_qualification.json'
    if qualification_started is not None and receipt.stat().st_mtime < qualification_started:
        raise ValueError('Refusing stale qualification receipt from an earlier run')
    qualification = json.loads(receipt.read_text(encoding='utf-8'))
    if not qualification.get('success') or qualification.get('native_shape') != [22000, 22000]:
        raise ValueError('Full native qualification did not pass')
    metadata = Path(qualification['metadata'])
    if not metadata.is_file() or not (metadata.parent / 'geo_color.tif').is_file():
        raise FileNotFoundError('Qualified native source is unavailable')
    if json.loads(metadata.read_text(encoding='utf-8')).get('observation_support_version') != 2:
        raise ValueError('Qualified source has rejected legacy observation coverage')
    # The qualifier may be completing its final process teardown; no duplicate job.
    command = [str(engine), 'native-pipeline', '--root', str(root), '--blender', str(blender)]
    with (reports / f'native_pipeline_{label}.stdout.log').open('a', encoding='utf-8') as stdout, \
            (reports / f'native_pipeline_{label}.stderr.log').open('a', encoding='utf-8') as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=engine.parent)
        status('native_pipeline_running', launcher_pid=child.pid, command=command)
        code = child.wait()
    status('native_pipeline_exited', exit_code=code,
           delivery_manifest_present=(root / 'exports/earth_native_only_v1/delivery_manifest.json').is_file())
    if code:
        raise SystemExit(code)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--blender', required=True)
    parser.add_argument('--wait-pid', required=True, type=int)
    parser.add_argument('--label', default='v20')
    args = parser.parse_args()
    main(args.root, args.engine, args.blender, args.wait_pid, args.label)
