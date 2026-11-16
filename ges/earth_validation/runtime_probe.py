"""Exercise packaged C extensions and a real stock composite, not just --help."""
import json
from pathlib import Path
import sys
import numpy as np
from netCDF4 import Dataset
from pyproj import Transformer
from .archive import target_for,sha
from .io_paths import reader_paths
from .stock import configure,open_scene,export_scene
from .project import save


def verify(root):
    root=Path(root); configure(root)
    import pyresample
    import dask.array as da
    from .spill import bounded_compute
    if pyresample.CHUNK_SIZE!=512:
        raise RuntimeError('Pyresample imported before the 512-pixel startup configuration')
    with bounded_compute(root,limit=8192) as cache:
        array=da.arange(128*128,dtype=np.float64).reshape(128,128).rechunk((32,32))
        actual=(array+1).compute()
        if not np.array_equal(actual,np.arange(128*128).reshape(128,128)+1) or cache.written_bytes==0:
            raise RuntimeError('Packaged lossless Dask spill failed')
        spill_bytes=cache.written_bytes
    from .gpu import device
    from .fusion import fuse
    gpu=device()
    sample_pixels=np.full((8,8,4),255,np.uint8)
    sample_lon,sample_lat=np.meshgrid(np.linspace(-10,10,8),np.linspace(-10,10,8))
    cpu=fuse([(sample_pixels,0)],sample_lon,sample_lat)
    cuda=fuse([(sample_pixels,0)],sample_lon,sample_lat,backend='cuda')
    if not all(np.array_equal(a,b) for a,b in zip(cpu,cuda)):
        raise ValueError('Packaged CUDA fusion parity check failed')
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    descriptor=next(s for s in plan['scenes'] if s['sensor']=='goes16')
    record=next(r for r in plan['records'] if r['scene_id']==descriptor['scene_id'] and r.get('band')=='C01')
    source=reader_paths(root,descriptor['scene_id'],[target_for(root,record)])[0]
    with Dataset(str(source)) as data:
        variable=data['Rad']; h,w=variable.shape
        sample=np.ma.filled(variable[h//2:h//2+8,w//2:w//2+8],np.nan)
        if not np.isfinite(sample).any(): raise ValueError('No finite ABI sample')
    descriptor=next(s for s in reversed(plan['scenes']) if s['sensor']=='himawari8')
    scene,records=open_scene(root,plan,descriptor); area=scene['B03'].attrs['area']
    x,y=Transformer.from_crs('EPSG:4326',area.crs,always_xy=True).transform(127,25)
    col=int((x-area.area_extent[0])/area.pixel_size_x)//4*4
    row=int((area.area_extent[3]-y)/area.pixel_size_y)//4*4
    crop=area[slice(row-32,row+32),slice(col-32,col+32)]
    kind='runtime_probe_'+sha(Path(sys.executable))[:12]
    metadata=export_scene(root,plan,descriptor,crop,kind,
        root/'raw/references/blackmarble_2016_500m/global_500m.vrt',native=True,opened=(scene,records))
    report={'packaged':bool(getattr(sys,'frozen',False)),'executable':sys.executable,
        'abi_shape':[h,w],'finite_abi_sample':int(np.isfinite(sample).sum()),
        'native_stock_composite':str(metadata),'gpu':gpu,'cuda_kernel_and_fusion_passed':True,'success':True}
    report.update(pyresample_import_chunk=pyresample.CHUNK_SIZE,lossless_array_spill_passed=True,
                  spill_smoke_written_bytes=spill_bytes)
    save(root/'reports/engine_runtime.json',report); print(json.dumps(report,ensure_ascii=False),flush=True)
    return report
