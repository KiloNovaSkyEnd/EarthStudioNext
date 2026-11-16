import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='Bounded H9 JPEG + independent ground-background production')
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--utc',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--quality',type=int,default=95)
    parser.add_argument('--night-metres',type=int,default=1000)
    parser.add_argument('--keep-l1',action='store_true')
    parser.add_argument('--keep-intermediates',action='store_true')
    parser.add_argument('--inputs',type=Path)
    parser.add_argument('--night-reference',type=Path)
    parser.add_argument('--night-mode',choices=('geocolor','ai-vis','ai-vis-ir'),default=None)
    args=parser.parse_args()
    from .h9_job import run
    import json
    paths=json.loads(args.inputs.read_text(encoding='utf-8')) if args.inputs else None
    run(args.source_root,args.reference,args.utc,args.output,args.quality,args.night_metres,
        args.keep_l1,args.keep_intermediates,paths,args.night_reference,args.night_mode)


if __name__=='__main__': main()
