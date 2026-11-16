"""Real original-grid page for Blender wiring; explicitly a regional qualification."""
import argparse
import json
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges.earth_validation.native_cells import write
from ges.catalog import utc_time
from ges.solar import sun_direction
parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True)
args=parser.parse_args(); root=Path(args.root)
metadata=root/'processed/stock_geocolor/himawari8_20220901T0500Z/camera_cell_v1_l0_c61_r22/metadata.json'
utc='2022-09-01T05:00:00Z'
page=write(root,[metadata],61,22,1,utc,namespace='native_earth_qualification_v1')
assert page['valid_fraction']>.99
assets={'nodes':[{'nominal_utc':utc,'index':1,'sun':sun_direction(utc_time(utc)).tolist()}],
        'cells':[[61,22]],'hold':4,'namespace':'native_earth_qualification_v1',
        'engine':'qualification-only','global_native_precomputed':False,
        'limits':'Regional actual native page only; not final full globe or full timeline.'}
target=root/'reports/native_only_qualification_assets.json'
target.write_text(json.dumps(assets,indent=2),encoding='utf-8')
print(json.dumps(page,indent=2)); print(target)
