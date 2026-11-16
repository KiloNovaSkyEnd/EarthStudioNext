"""Serializable tasks, unique output folders and durable task records; no Qt."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import uuid

ROOT = Path(__file__).resolve().parents[2]
ACTIONS = {'search', 'download', 'render', 'mosaic', 'blender', 'export',
           'meteosat-search', 'meteosat-download', 'daylight', 'day-night', 'blend-ir', 'render-batch'}


@dataclass(frozen=True)
class Job:
    action: str
    options: dict
    directory: Path

    @classmethod
    def create(cls, action, options, processed_root):
        if action not in ACTIONS:
            raise ValueError('Unknown desktop action')
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_') + uuid.uuid4().hex[:8]
        directory = Path(processed_root) / 'desktop_jobs' / name
        directory.mkdir(parents=True, exist_ok=False)
        job = cls(action, dict(options), directory)
        job.update('queued')
        return job

    def update(self, status, **extra):
        record = {**asdict(self), 'directory': str(self.directory), 'status': status, **extra}
        path = self.directory / 'job.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    def command(self, python):
        return str(python), ['-u', '-m', 'ges.desktop.worker', str(self.directory / 'job.json')]
