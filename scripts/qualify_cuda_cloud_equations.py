"""GPU kernels against the installed original Satpy equations, including NaNs."""
from pathlib import Path
import sys,json,os,time
import numpy as np
import dask.array as da
import xarray as xr
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from satpy.composites.mask import LowCloudCompositor,HighCloudCompositor
from ges.earth_validation.satpy_execution import BoundedLowCloudCompositor,BoundedHighCloudCompositor
from pyresample.geometry import AreaDefinition

area=AreaDefinition('test','','',{'proj':'geos','lon_0':140.7,'h':35785863,'a':6378137,'b':6356752.3,'sweep':'y'},256,192,(-5000000,-5000000,5000000,5000000))
rng=np.random.default_rng(17);records=[]
for dtype in [np.float32,np.float64]:
    values=[rng.uniform(-2,8,(192,256)).astype(dtype),rng.choice([229.,230.,231.,np.nan],(192,256)).astype(dtype),
        rng.choice([0.,100.,50.,np.nan],(192,256)).astype(dtype)]
    values[0][3:8,5:9]=np.nan
    inputs=[xr.DataArray(da.from_array(v,chunks=(48,64)),dims=('y','x'),coords={'y':np.arange(192),'x':np.arange(256)},attrs={'area':area,'name':f'band{i}'}) for i,v in enumerate(values)]
    for kind,original,accelerated,args,options in [
        ('low',LowCloudCompositor,BoundedLowCloudCompositor,inputs,dict(values_land=100)),
        ('high',HighCloudCompositor,BoundedHighCloudCompositor,[inputs[1].copy(data=da.from_array(rng.uniform(180,320,(192,256)).astype(dtype),chunks=(48,64)))],{})]:
        os.environ.pop('EARTHSTUDIO_H9_CUDA_CLOUDS',None)
        reference=original(kind,**options)(args).compute()
        os.environ['EARTHSTUDIO_H9_CUDA_CLOUDS']='1'
        actual=accelerated(kind,**options)(args).compute()
        a,b=reference.values,actual.values
        assert np.array_equal(np.isnan(a),np.isnan(b)),(kind,'NaN mask changed')
        maximum=float(np.nanmax(np.abs(a-b)))
        assert maximum<np.finfo(dtype).eps*16,(kind,dtype,maximum)
        assert reference.attrs==actual.attrs,(reference.attrs,actual.attrs)
        records.append(dict(kind=kind,dtype=str(dtype),max_float_error=maximum,identical_values=bool(np.array_equal(a,b,equal_nan=True))))
        print('CUDA_EQUATION',records[-1],flush=True)
from ges.earth_validation.resources import gpu_sample
out=root/'data/projects/H9_20261020_UTCminus7_1100_1700/reports/cuda_cloud_equation_qualification.json'
out.write_text(json.dumps(dict(records=records,gpu=gpu_sample),indent=2),encoding='utf-8')
