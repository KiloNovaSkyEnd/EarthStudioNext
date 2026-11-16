"""Inspect installed recipes, not the present-day satellite fleet."""
import hashlib
import json
from pathlib import Path
import satpy
import yaml
from .autoprocess import audit_archive
from .project import save

SENSORS = {'himawari8': 'ahi', 'goes16': 'abi', 'goes17': 'abi',
           'meteosat_zero': 'seviri', 'meteosat_iodc': 'seviri'}


def inspect(root):
    root = Path(root)
    plan = json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    configs = Path(satpy.__file__).parent/'etc/composites'
    sources = []
    project = json.loads((root/'project.json').read_text(encoding='utf-8'))
    for source, instrument in SENSORS.items():
        path = configs/f'{instrument}.yaml'
        # BaseLoader reads tag names without instantiating arbitrary Python tags.
        recipe = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
        supported = 'geo_color' in recipe.get('composites', {})
        sources.append({'source': source, 'instrument': instrument,
            'stock_geocolor_available': supported,
            'allowed_natural_color_exception':instrument=='seviri' and project.get('allow_seviri_natural_color',False),
            'recipe_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'unique_archived_scenes': len({s['scene_id'] for s in plan['scenes'] if s['sensor']==source}),
            'reason': None if supported else
                ('Explicitly authorized observed natural-colour adaptation; not stock GeoColor' if project.get('allow_seviri_natural_color') else
                 'Installed Satpy has no stock geo_color recipe for this historical sensor; no substitute enabled')})
    problems = audit_archive(root, plan)
    result = {'satpy_version': satpy.__version__, 'sources': sources,
        'archive_objects': len(plan['records']), 'archive_bytes': plan['total_raw_bytes'],
        'archive_receipt_problems': problems, 'nominal_nodes': len(plan['frames']),
        'source_gaps': plan['failures'], 'global_acceptance_passed': False,
        'global_blockers': [s['source'] for s in sources if not (s['stock_geocolor_available'] or s['allowed_natural_color_exception'])],
        'limits': 'Recipe support and receipt/size checks only; no pixel coverage, checksum reread or visual acceptance claim'}
    save(root/'reports'/'stock_capabilities.json', result)
    return result
