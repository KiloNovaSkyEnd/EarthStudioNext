"""Existing GOES17 measured RGB only; no download or invented color bands."""
from pathlib import Path
from ges.daylight import render_daylight

ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    manifest=next((ROOT/'data/raw').glob('goes17_20201029T1640*/scene.json'))
    print(render_daylight(manifest,ROOT/'data/processed/day_night_v8/daylight_west',8192),flush=True)
