"""GPU child entry; explicit frame/work/resource identities, no research-directory imports."""
import argparse
from datetime import datetime
from pathlib import Path
from . import infer

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--work',type=Path,required=True);parser.add_argument('--utc',required=True)
    args=parser.parse_args();infer.ROOT=args.work.resolve()
    infer.ASSET_ROOT=Path(__file__).resolve().parents[3]/'resources/models/aivis'
    infer.WEIGHT=infer.ASSET_ROOT/'aivis_setup/weights/aivis_1_0.safetensors'
    infer.WHEN=datetime.fromisoformat(args.utc.replace('Z','+00:00'))
    infer.main()
if __name__=='__main__':main()
