"""Offline package of exact native H9 pages and independently editable cameras."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ges_next.isolation import require_writable


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--demonstrations', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = require_writable(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if (out/'package_manifest.json').exists():
        raise FileExistsError('Committed package is preserved; choose a new output folder')
    assets = out/'assets'
    assets.mkdir(exist_ok=True)
    master = json.loads((args.source/'native_master.json').read_text(encoding='utf-8'))
    if master['utc'] != '2026-10-20T22:40:00Z' or master['shape'] != [22000, 22000] or len(master['tiles']) != 16:
        raise ValueError('Exact requested native disk is required')
    size = sum((args.source/t['path']).stat().st_size for t in master['tiles'])
    if shutil.disk_usage(out).free < size+16*1024**3:
        raise ValueError('Insufficient storage reserve')
    records = []
    for tile in master['tiles']:
        source, target = args.source/tile['path'], assets/tile['path']
        if digest(source) != tile['sha256']:
            raise ValueError('Native source hash mismatch')
        if not target.exists():
            shutil.copy2(source, target)
        if digest(target) != tile['sha256']:
            raise ValueError('Packaged native image hash mismatch')
        records.append(dict(path='assets/'+tile['path'], bytes=target.stat().st_size, sha256=tile['sha256']))
    bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
    if args.demonstrations:
        demo = json.loads(args.demonstrations.read_text(encoding='utf-8'))
        extra = [t for t in demo['tracks'] if t['keyframeTrack']['id'] in ('A', 'B', 'C')]
        bundle['tracks'].extend(extra)
        bundle['timelineProject']['tracks'].extend(t['keyframeTrack'] for t in extra)
        for track in bundle['tracks']:
            track['timelineProject'] = bundle['timelineProject']
    # Ensure a true single-scan package; requested animation times cannot invent scans.
    if any(s.get('utc') != master['utc'] for t in bundle['tracks'] for s in t['samples']):
        raise ValueError('Camera observation time does not match the material')
    from ges.solar import sun_direction
    import pyorbital
    sun = sun_direction(datetime.fromisoformat(master['utc'].replace('Z', '+00:00'))).tolist()
    metadata = dict(schema='earthstudio.blender.native_static.v1', utc=master['utc'],
                    scanStartUtc=master['sourceBands']['B03']['startUtc'], scanEndUtc=master['sourceBands']['B03']['endUtc'],
                    earthModel='WGS84', nativeShape=master['shape'], nativeBytes=size,
                    sun=sun, astronomy='pyorbital '+pyorbital.__version__, files=records,
                    cameraTracks=len(bundle['tracks']), effects=bundle['timelineProject'].get('effects', {}),
                    limits=master['limits'], downloads=0, weatherAnimated=False)
    for name, value in [('native_master.json', master), ('camera_bundle.json', bundle), ('package_manifest.json', metadata)]:
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(package=str(out), bytes=size, tracks=len(bundle['tracks']), sun=sun)), flush=True)


if __name__ == '__main__':
    main()
