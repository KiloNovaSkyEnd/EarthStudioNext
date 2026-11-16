"""Explicit, nondestructive sequence assembly for the native desktop."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from .collection import from_queue
from .package import build
from .preview import prepare


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--queue',type=Path);group.add_argument('--packages',type=Path,nargs='+')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--step-minutes',type=int,default=10)
    parser.add_argument('--blender',default=os.environ.get('EARTHSTUDIO_BLENDER','blender.exe'))
    parser.add_argument('--update-blend',type=Path)
    args=parser.parse_args()
    def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
    try:
        packages,step=from_queue(args.queue) if args.queue else (args.packages,args.step_minutes)
        artist_hash=None
        if args.update_blend:
            from ges_next.production.assets import digest
            artist_hash=digest(args.update_blend)
        first=min(packages,key=lambda p:json.loads((p/'commit.json').read_text(encoding='utf-8'))['utc'])
        from .template import select
        template=select(first)
        build(packages,args.output,step,emit);prepare(args.output,report=emit)
        nodes=json.loads((args.output/'sequence_manifest.json').read_text(encoding='utf-8'))['nodes']
        if nodes:
            root=Path(__file__).resolve().parents[2]
            emit(dict(phase='building-layered-animation'))
            if args.update_blend:
                with (args.output/'artist_update.log').open('w',encoding='utf-8') as log:
                    subprocess.run([args.blender,'--background',str(args.update_blend.resolve()),'--disable-autoexec','--python-exit-code','1',
                        '--python',str(root/'scripts/blender_update_layered_sequence.py'),'--',str(args.output.resolve())],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
                if digest(args.update_blend)!=artist_hash:raise ValueError('Artist source changed during update')
                with (args.output/'artist_reopen.log').open('w',encoding='utf-8') as log:
                    subprocess.run([args.blender,'--background',str(args.output.resolve()/'EarthStudio_保留编辑_更新天气.blend'),
                        '--disable-autoexec','--python-exit-code','1','--python',str(root/'scripts/blender_verify_artist_update.py')],
                        cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
                emit(dict(phase='artist-copy-ready',folder=str(args.output.resolve()),nodes=len(nodes),artist_edits_preserved=True))
            with (args.output/'blender_animation.log').open('w',encoding='utf-8') as log:
                subprocess.run([args.blender,'--background',str(template),'--disable-autoexec','--python-exit-code','1','--python',
                    str(root/'scripts/blender_build_layered_sequence.py'),'--',str(args.output.resolve())],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
            emit(dict(phase='verifying-layered-animation'))
            with (args.output/'animation_reopen.log').open('w',encoding='utf-8') as log:
                subprocess.run([args.blender,'--background',str(args.output.resolve()/('EarthStudio_JPG_单帧.blend' if len(nodes)==1 else 'EarthStudio_JPG_动画.blend')),'--disable-autoexec','--python-exit-code','1',
                    '--python',str(root/'scripts/blender_verify_layered_sequence.py'),'--',str(args.output.resolve())],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
        if len(nodes)==1:
            from .still import export_still
            export_still(args.output,report=emit)
        emit(dict(phase='sequence-ready',folder=str(args.output.resolve()),nodes=len(nodes)))
    except Exception as error:
        emit(dict(phase='error',error=str(error)));raise SystemExit(1)


if __name__=='__main__':main()
