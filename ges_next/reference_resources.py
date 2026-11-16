"""Locate read-only auxiliary references across standalone and embedded engines."""
from pathlib import Path

MASK=Path('satpy_geocolor_v060/composites/gshhs_land_water_mask_3km_i.tif')

def resolve(engine=None):
    root=Path(engine).resolve() if engine is not None else Path(__file__).resolve().parents[1]
    for parent in (root,*root.parents):
        for reference in (parent/'data/raw/reference',parent/'GlobalSatelliteEarthStudio/data/raw/reference'):
            if (reference/MASK).is_file():
                return reference.resolve()
    raise ValueError('未找到地表辅助参考（gshhs_land_water_mask_3km_i.tif）。请恢复软件共享参考目录；尚未开始新的L1下载，已有输入保留。')
