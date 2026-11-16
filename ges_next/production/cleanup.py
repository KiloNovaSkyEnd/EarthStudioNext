"""Owned-job cleanup in an isolated process; all existing gates remain mandatory."""
import argparse,json,os,time
from pathlib import Path
from ges_next.production.assets import write_json
from ges_next.production.journal import Journal
from ges_next.production.retention import Retention
from ges_next.production.owned_files import CleanupSession
from ges_next.production.validation_session import ValidationSession
from ges_next.isolation import require_writable


def run(package):
    package=require_writable(package)
    began=time.perf_counter();journal=Journal(package.parent/'production_journal.sqlite')
    try:
        row=journal.db.execute('SELECT id FROM jobs WHERE root=?',(str(package),)).fetchone()
        if row is None:raise ValueError('Cleanup cannot adopt an unknown job')
        data=json.loads((package/'commit.json').read_text(encoding='utf8'));utc=data['utc']
        print(json.dumps(dict(phase='checking-owned-cleanup',utc=utc,pid=os.getpid())),flush=True)
        retention=Retention(journal)
        with ValidationSession(),CleanupSession() as checks:
            plan=retention.plan(row['id'],utc)
            write_json(package/'cleanup_plan.json',plan)
            result=retention.execute(plan)
            write_json(package/'cleanup_result.json',result)
        write_json(package/'cleanup_validation.json',dict(**checks.summary(),seconds=time.perf_counter()-began,
            pid=os.getpid(),isolated_process=True))
        print(json.dumps(dict(phase='owned-cleanup-complete',utc=utc,deleted_files=result['deleted_files'])),flush=True)
        return result
    finally:journal.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('package',type=Path)
    run(parser.parse_args().package)


if __name__=='__main__':main()
