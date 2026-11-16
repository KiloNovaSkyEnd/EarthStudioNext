"""Cache-only, unmodified installed Satpy GeoColor; no project colour imports."""
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    raw = ROOT/'data/raw/himawari9_20261020T192000Z'
    out = ROOT/'data/processed/satpy_night_review_20261020T1920Z'
    out.mkdir(exist_ok=True)
    destination = out/'geo_color.png'
    if destination.exists() and (out/'metadata.json').exists():
        assert sha(destination) == json.loads((out/'metadata.json').read_text())['sha256']
        print('VERIFIED EXISTING', destination, flush=True)
        return
    assert shutil.disk_usage(ROOT).free > 15_000_000_000
    scratch = out/'hsd'
    scratch.mkdir(exist_ok=True)
    ref = ROOT/'data/raw/reference'
    os.environ['PSP_CONFIG_FILE'] = str(ref/'pyspectral/pyspectral.yaml')
    os.environ['OMP_NUM_THREADS'] = '2'
    os.environ['PYTROLL_CHUNK_SIZE'] = '1024'
    import dask
    import satpy
    from satpy import Scene
    from PIL import Image
    satpy.config.set(data_dir=str(ref/'satpy_geocolor_v060'),download_aux=False,tmp_dir=str(scratch))
    dask.config.set(scheduler='threads',num_workers=2,**{'array.chunk-size':'32MiB'})
    files = sorted(raw.glob('*.bz2'))
    assert len(files) == 60
    scene = Scene(reader='ahi_hsd',filenames=[str(p) for p in files])
    scene.load(['B01','B02','B03','B04','B07','B13'])
    target = scene['B13'].attrs['area']
    print('NATIVE GRID',target.shape,flush=True)
    res = scene.resample(target,resampler='native')
    res.load(['geo_color'])
    ancillary = [k for k in res.keys() if res[k].attrs.get('area') != target]
    if ancillary:
        aligned = res.resample(target,datasets=ancillary,generate=False,resampler='nearest',radius_of_influence=6000)
        for key in ancillary:
            res[key] = aligned[key]
    res.generate_possible_composites(unload=True)
    assert 'geo_color' in res
    print('SAVE STOCK GEO_COLOR',flush=True)
    partial = out/'geo_color.part.png'
    res.save_dataset('geo_color',filename=str(partial),writer='simple_image',fill_value=0)
    with Image.open(partial) as image:
        assert image.size == (target.width,target.height)
        image.verify()
    partial.replace(destination)
    record = dict(satpy_version=satpy.__version__,composite='geo_color',official_config_unmodified=True,
        nominal_utc='2026-10-20T19:20:00Z',start_utc=str(res['geo_color'].attrs['start_time']),
        end_utc=str(res['geo_color'].attrs['end_time']),shape=list(target.shape),projection=target.crs.to_dict(),
        extent=list(target.area_extent),sha256=sha(destination),
        method='Stock Scene geo_color, stock enhancements, native 2km band alignment and nearest static ancillary registration',
        source_hashes={p.name:sha(p) for p in files},
        limits='Himawari visible hemisphere; 2km review grid; Satpy static 2016 Black Marble, not live lights')
    (out/'metadata.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print('DONE',destination,flush=True)


if __name__ == '__main__':
    main()
