import argparse
import os
from . import bootstrap  # noqa: F401
from pathlib import Path
from .project import initialize


def main():
    import sys
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['inventory', 'download', 'prepare', 'autoprocess', 'capabilities', 'night-background', 'stock-pilot', 'stock-export', 'stock-pipeline', 'stock-sequence', 'camera-tiles', 'full-pipeline', 'native-pipeline', 'runtime-check'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--download-pid', type=int)
    parser.add_argument('--blender')
    parser.add_argument('--existing-night-d1')
    parser.add_argument('--request')
    args = parser.parse_args()
    from ges_next.isolation import require_writable
    root = require_writable(args.root)
    initialize(root)
    os.environ['TMP'] = os.environ['TEMP'] = str(root / 'scratch')
    if args.stage == 'runtime-check':
        from .runtime_probe import verify
        verify(root)
    if args.stage in ('full-pipeline','native-pipeline'):
        if not args.blender: parser.error('full-pipeline requires --blender')
        import json
        project=json.loads((root/'project.json').read_text(encoding='utf-8'))
        if args.stage=='native-pipeline' or project.get('delivery_mode')=='native_only_global':
            from .native_pipeline import run
        else:
            from .full_pipeline import run
        run(root,args.blender)
    if args.stage == 'camera-tiles':
        if not args.request: parser.error('camera-tiles requires --request')
        from .camera_tiles import process
        process(root,args.request)
    if args.stage == 'stock-sequence':
        from .sequence_job import run
        run(root)
    if args.stage == 'capabilities':
        from .capabilities import inspect
        result = inspect(root)
        print('Stock GeoColor global blockers:', result['global_blockers'])
    if args.stage == 'night-background':
        from .night_background import acquire
        print(acquire(root, args.existing_night_d1))
    if args.stage == 'stock-pilot':
        from .stock_job import run
        run(root)
    if args.stage == 'stock-export':
        if not args.blender: parser.error('stock-export requires --blender')
        from .stock_export import export
        print(export(root,args.blender))
    if args.stage == 'stock-pipeline':
        if not args.blender: parser.error('stock-pipeline requires --blender')
        from .archive import download
        from .night_background import acquire
        from .stock_job import run
        from .stock_export import export
        if not (root/'inventory.json').is_file():
            raise FileNotFoundError('Existing validation inventory required; create and verify a source plan first')
        download(root,args.workers)
        acquire(root,args.existing_night_d1)
        run(root)
        print(export(root,args.blender))
    if args.stage == 'inventory':
        from .inventory import build
        build(root)
    if args.stage == 'download':
        from .archive import download
        download(root, args.workers, args.pilot)
    if args.stage == 'prepare':
        from .prepare import prepare
        prepare(root, pilot=args.pilot)
    if args.stage == 'autoprocess':
        if not args.download_pid or not args.blender:
            parser.error('autoprocess requires --download-pid and --blender')
        from .autoprocess import run
        run(root, args.download_pid, args.blender)


if __name__ == '__main__':
    main()
