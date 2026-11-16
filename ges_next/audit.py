"""Local installed-reader audit; does not open/download scientific scenes."""
import json
from pathlib import Path
import hashlib
from .isolation import ROOT,require_writable


def run():
    import satpy
    import yaml
    config=Path(satpy.__file__).parent/'etc'
    rows=[]
    for instrument,reader in [('ahi','ahi_hsd'),('abi','abi_l1b'),('fci','fci_l1c_nc'),('seviri','seviri_l1b_hrit')]:
        path=config/'composites'/f'{instrument}.yaml'
        recipe=yaml.load(path.read_text(encoding='utf-8'),Loader=yaml.BaseLoader)
        rows.append(dict(instrument=instrument,reader=reader,reader_config_present=(config/'readers'/f'{reader}.yaml').exists(),
            stock_geo_color='geo_color' in recipe.get('composites',{}),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            real_scene_tested=False))
    result=dict(product='Earth Studio Next',satpy_version=satpy.__version__,sources=rows,
        native_only_global=True,night_background_required_m=500,night_background_verified=False,
        runtime='shared development interpreter; independent scientific EXE not packaged yet',
        source_quality_accepted=False,legacy_outputs_read_only=True)
    path=require_writable(ROOT/'reports/next_capabilities.json')
    path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False,indent=2))
