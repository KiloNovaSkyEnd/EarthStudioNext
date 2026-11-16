"""Install only completed, byte-identical, independently reopened local timing evidence."""
import json,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ges_next.pipeline import runner
from ges_next.pipeline.measured_defaults import host_identity
from ges_next.production.assets import write_json,digest

run=Path(sys.argv[1]).resolve();summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
status=json.loads((run/'status.json').read_text(encoding='utf-8'));receipt=json.loads((run/'source_receipt.json').read_text(encoding='utf-8'))
assert status['phase']=='complete' and status['source_snapshot_unchanged']
assert all(digest(ROOT/name)==sha for name,sha in receipt['engine'].items())
queue,plan,state=runner.load(Path(receipt['live_queue']))
assert runner.accepted(queue,state)
assert state['phase']=='paused-user' or (state['phase']=='parallel-running' and
    'recommended_max_compute' in state.get('concurrency',{}) and 'verification_budget_bytes' in state.get('concurrency',{})), 'Queue does not support safe live configuration'
profile=dict(Format='jpeg',HimawariDiskSize=11000,JpegQuality=95,NightLightMetres=1000)
assert all(plan['project']['Production'].get(key)==value for key,value in profile.items())
for case in status['results']:
    for index,job in enumerate(case.get('jobs',[])):
        package=run/case['case']/f'job_{index}'
        assert job['science']['asset_hashes_identical']
        journal=runner.journal_for(package)
        try:
            row=journal.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()
            journal.gate(row['id'],receipt['utc'])
        finally:journal.close()
engine={name:sha for name,sha in receipt['engine'].items() if not name.startswith('reports/')}
for file in [*(ROOT/'ges_next/production').glob('*.py'),ROOT/'scripts/blender_build_production_layers.py',
             ROOT/'scripts/blender_verify_production_layers.py',ROOT/'ges_next/pipeline/concurrency.py',
             ROOT/'ges_next/pipeline/measured_defaults.py']:
    engine[file.relative_to(ROOT).as_posix()]=digest(file)
data=dict(schema='earthstudio.h9_11k_throughput.v1',host=host_identity(),profile=profile,engine=engine,
    recommended_max_compute=summary['recommended_max_compute'],thread_profiles=summary['thread_profiles'],
    decode_threads=4,science_by_threads=summary['science_by_threads'],verification_peaks=summary['verification_peaks'],
    science_margin=1.15,
    all_assets_identical=True,independent_reopen_verified=True,evidence=dict(path=str(run/'summary.json'),
        sha256=digest(run/'summary.json'),fixed_utc=receipt['utc'],limits=summary['limits']))
destination=ROOT/'resources/performance/h9_11k_throughput.json'
if destination.exists() and not (run/'previous_host_qualification.json').exists():
    write_json(run/'previous_host_qualification.json',json.loads(destination.read_text(encoding='utf-8')))
write_json(destination,data)
execution=json.loads((queue/'execution.json').read_text(encoding='utf-8'))
if not (run/'previous_execution.json').exists():write_json(run/'previous_execution.json',execution)
# Preserve the user's mode and manually chosen limit; recommendations constrain automatic mode only.
execution.update(recommended_max_compute=data['recommended_max_compute'],thread_profiles=data['thread_profiles'],decode_threads=4)
write_json(queue/'execution.json',execution)
write_json(ROOT/'reports/m8_performance/activation.json',dict(utc=datetime.now(timezone.utc).isoformat(),queue=str(queue),
    completed=len(state['completed']),comparison=str(run),execution=execution,
    status='hot-settings-published' if state['phase']=='parallel-running' else 'ready-to-resume-original-queue'))
print(json.dumps(dict(recommended_max_compute=data['recommended_max_compute'],thread_profiles=data['thread_profiles'],completed=len(state['completed'])),ensure_ascii=False))
