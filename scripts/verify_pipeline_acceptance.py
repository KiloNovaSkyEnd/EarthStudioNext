"""Summarize the real bounded M4 checkpoint without approving/deleting any real data."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.pipeline.runner import load,package_for,journal_for
from ges_next.production.assets import digest,verify_assets,write_json


def main():
    root=Path(__file__).resolve().parents[1]
    queue=root/'data/pipeline_acceptance/H9_cached_first_sample_M4_r2'
    _,plan,state=load(queue)
    assert state['phase']=='awaiting-quality' and state['completed']==[]
    assert len(plan['steps'])==2 and state['first_sample']==plan['steps'][0]['utc']
    package=package_for(queue,state['first_sample']);commit=json.loads((package/'commit.json').read_text(encoding='utf-8'))
    assert commit['grid']['shape']==[11000,11000]
    verify_assets(package,commit['assets']);verify_assets(package,[commit['rebuild_recipe']])
    assert not package_for(queue,plan['steps'][1]['utc']).exists()
    assert not (queue/'quality_acceptance.json').exists() and not (package/'cleanup_result.json').exists()
    j=journal_for(package)
    try:
        job=j.db.execute('SELECT * FROM jobs WHERE root=?',(str(package),)).fetchone()
        assert job['owned']==1 and job['approved']==0
        assert j.step(job['id'],state['first_sample'])['state']=='verified'
        reused=j.db.execute("SELECT * FROM sources WHERE role='reused'").fetchall()
        assert len(reused)==60
        for item in reused:
            receipt=json.loads(Path(item['path']+'.json').read_text(encoding='utf-8'))
            assert item['owner'] is None and item['deleted']==0 and digest(item['path'])==receipt['sha256']
        temporary=j.db.execute("SELECT COUNT(*) FROM sources WHERE role='temporary'").fetchone()
    finally:j.close()
    previous=root/'data/production_jobs/H9_20261020T1300Z_JPEG95_M2'
    old=json.loads((previous/'commit.json').read_text(encoding='utf-8'))
    identical={a['role']:any(b['role']==a['role'] and b['sha256']==a['sha256'] for b in old['assets']) for a in commit['assets']}
    status=json.loads((package/'status.json').read_text(encoding='utf-8'))
    preserved={
        'original_dynamic_blend':digest(root/'data/exports/H9_20261020_12h_Blender_v1/Earth_Studio_动态天气与自由运镜.blend'),
        'previous_layered_blend':digest(previous/'EarthStudio_JPEG_独立灯光.blend')}
    assert preserved['original_dynamic_blend']=='a95115c14bcbe08c3e93d2f89ae4a957b616044a37f946e133aa0f8f8382182c'
    assert preserved['previous_layered_blend']=='b0457126a47e1e9c4beea7707ab58c1921c3bcfe1d61b492d29cb6984f67fe68'
    value=dict(real_scans_produced=1,queued_scans=2,second_scan_started=False,phase=state['phase'],
        shape=commit['grid']['shape'],asset_bytes=sum(a['bytes'] for a in commit['assets']),quality=commit['quality'],
        source_files_reused_readonly=60,new_payload_bytes=0,historical_sources_rehashed_and_unchanged=True,
        real_cleanup_executed=False,human_quality_accepted=False,temporary_files_retained=temporary[0],science_seconds=status['elapsed_seconds'],
        identical_to_previous_M2_assets=identical,blender_reopen=json.loads((package/'blender_reopen.json').read_text(encoding='utf-8')),
        preserved=preserved,
        tests=dict(pipeline_fixtures=16,production=26,satellite_selection=7,bridge=7,native_model=28,native_services=13),
        limitations=['No new online payload download in bounded validation','Native mouse-click acceptance pending',
            'New layered sequence continuous playback and single animated Blender project pending'])
    write_json(root/'reports/native_pipeline_m4/acceptance.json',value)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
