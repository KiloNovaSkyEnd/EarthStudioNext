"""Durable per-request catalog evidence, independent of project time ranges.

Only complete/definitive records are reused. Transport/permission failures are
retried. A refresh bypasses evidence without destroying previous inventories.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .inventory_selection import groups
from .selection import utc


def contract():
    # Changes to bands, matching windows or satellite selection invalidate reuse.
    root = Path(__file__).parent
    return sha256(b''.join((root / name).read_bytes() for name in
        ('inventory_selection.py', 'noaa.py', 'selection.py'))).hexdigest()


class CatalogCache:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / 'catalog.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS evidence (key TEXT PRIMARY KEY, body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS imports (path TEXT PRIMARY KEY, stamp TEXT NOT NULL)')
        self.version = contract()
        self.hits = self.queries = 0

    def close(self):
        self.db.close()

    def key(self, when, choices):
        return json.dumps([self.version, utc(when).isoformat(), list(choices)], separators=(',', ':'))

    def save(self, when, choices, record):
        state = record.get('state', 'available')
        if state not in ('available', 'missing', 'not-applicable'):
            return
        if state == 'available' and not record.get('native'):
            return
        clean = deepcopy(record)
        for field in ('region', 'requested_utc', 'additional_known_bytes', 'cache_hit'):
            clean.pop(field, None)
        clean['catalog_checked_utc'] = clean.get('catalog_checked_utc', datetime.now(timezone.utc).isoformat())
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO evidence VALUES (?, ?)',
                            (self.key(when, choices), json.dumps(clean, ensure_ascii=False)))

    def query(self, when, choices, client, query_fn, refresh=False):
        key = self.key(when, choices)
        row = None if refresh else self.db.execute('SELECT body FROM evidence WHERE key=?', (key,)).fetchone()
        if row:
            self.hits += 1
            return dict(json.loads(row[0]), cache_hit=True)
        self.queries += 1
        result = query_fn(when, choices, client)
        # A failed explicit refresh must not leave old evidence silently reusable.
        if refresh:
            with self.db:
                self.db.execute('DELETE FROM evidence WHERE key=?', (key,))
        self.save(when, choices, result)
        return dict(result, cache_hit=False)

    def import_inventories(self, projects):
        """Adopt existing partial M4/M5 inventories without network queries.

        Older inventories lack a cache contract; accept only the current native
        NOAA schema including exact required bands. Historical SEVIRI is retried.
        """
        from .noaa import AHI_BANDS, ABI_BANDS
        source=Path(projects)
        paths={source} if source.is_file() and source.name=='inventory.json' else set()
        if source.is_dir():
            for pattern in ('inventory.json','*/inventory.json','inventories/*/inventory.json','*/inventories/*/inventory.json','projects/*/inventories/*/inventory.json'):
                paths.update(source.glob(pattern))
        for path in sorted(paths, key=lambda p: p.stat().st_mtime_ns):
            stamp = str(path.stat().st_mtime_ns)
            if self.db.execute('SELECT stamp FROM imports WHERE path=?', (str(path),)).fetchone() == (stamp,):
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                spec = data.get('project_spec', {'SatelliteSelection': data.get('satellite_selection')})
                for record in data['records']:
                    when = utc(record['requested_utc'])
                    matches = [choices for region, choices in groups(spec, when) if region == record['region']]
                    native = record.get('native', {})
                    required = AHI_BANDS if str(record.get('source', '')).startswith('himawari') else ABI_BANDS
                    if len(matches) != 1 or record.get('state') != 'available' or set(native.get('bands', [])) != set(required):
                        continue
                    if not native.get('complete') or not native.get('keys'):
                        continue
                    # Never overwrite newer query evidence during migration.
                    if not self.db.execute('SELECT 1 FROM evidence WHERE key=?', (self.key(when, matches[0]),)).fetchone():
                        self.save(when, matches[0], record)
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO imports VALUES (?, ?)', (str(path), stamp))
            except (ValueError, KeyError, TypeError, OSError):
                continue
