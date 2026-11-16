"""Explicit Blender verification and new-job retention actions for one committed scan."""
import argparse
import json
from pathlib import Path
import subprocess
from .assets import verify_assets
from .journal import Journal
from .retention import Retention


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('--build-blender',action='store_true')
    parser.add_argument('--cleanup-plan',action='store_true')
    parser.add_argument('--cleanup',action='store_true')
    parser.add_argument('--accept-quality',action='store_true',help='Explicit human acceptance of this new JPEG profile')
    parser.add_argument('--blender',default='blender.exe')
    args=parser.parse_args()
    from ges_next.isolation import require_writable
    package=require_writable(args.package)
    commit=package/'commit.json'
    data=json.loads(commit.read_text(encoding='utf-8'))
    verify_assets(package,data['assets'])
    root=Path(__file__).resolve().parents[2]
    blend=package/'EarthStudio_JPEG_独立灯光.blend'
    if args.build_blender:
        from ges.solar import sun_direction
        from datetime import datetime
        from .assets import write_json
        write_json(package/'solar.json',dict(utc=data['utc'],sun_ecef=sun_direction(datetime.fromisoformat(data['utc'].replace('Z','+00:00'))).tolist()))
        template=root/'resources/blender/production_template.blend'
        if not template.is_file():raise FileNotFoundError('缺少应用Blender模板，请恢复resources/blender目录')
        operations=[]
        if not blend.exists(): operations.append(('build',template,'scripts/blender_build_production_layers.py',[str(package)]))
        operations.append(('reopen',blend,'scripts/blender_verify_production_layers.py',[]))
        for label,source,script,tail in operations:
            print(json.dumps(dict(phase='blender-'+label)),flush=True)
            with (package/('blender_'+label+'.log')).open('w',encoding='utf-8') as log:
                subprocess.run([args.blender,'--background',str(source),'--disable-autoexec',
                    '--python-exit-code','1','--python',str(root/script),'--',*tail],
                    cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
    journal=Journal(package.parent/'production_journal.sqlite')
    try:
        row=journal.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()
        if row is None: raise ValueError('Package has no production ownership journal')
        job=row['id'];utc=data['utc']
        if not journal.db.execute('SELECT 1 FROM steps WHERE job=? AND utc=?',(job,utc)).fetchone():
            journal.submit(job,utc,commit)  # Recover a crash between atomic commit and journal entry.
        journal.verify(job,utc,package/'blender_reopen.json')
        if args.accept_quality: journal.approve_profile(job,user_quality_accepted=True)
        if args.cleanup or args.cleanup_plan:
            retention=Retention(journal)
            if args.cleanup:
                plan=json.loads((package/'cleanup_plan.json').read_text(encoding='utf-8'))
                if plan['job']!=job or plan['utc']!=utc: raise ValueError('Cleanup plan belongs to another step')
            else:
                plan=retention.plan(job,utc)
                from .assets import write_json
                write_json(package/'cleanup_plan.json',plan)
            print(json.dumps(plan,ensure_ascii=False),flush=True)
            if args.cleanup:
                print(json.dumps(retention.execute(plan),ensure_ascii=False),flush=True)
        else: print(json.dumps(dict(phase='verified-awaiting-user-quality-acceptance',blend=str(blend)),ensure_ascii=False),flush=True)
    finally: journal.close()


if __name__=='__main__': main()
