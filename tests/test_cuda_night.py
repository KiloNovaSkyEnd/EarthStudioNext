import unittest
from unittest.mock import patch
import numpy as np
import dask.array as da
import xarray as xr
from pyresample.geometry import AreaDefinition
from satpy.composites.mask import LowCloudCompositor,HighCloudCompositor
from satpy.composites.fill import BackgroundCompositor
from ges.earth_validation.cuda_night import CudaNightBackgroundCompositor

class CudaNightTests(unittest.TestCase):
    def test_original_stock_night_layers_missing_pixels_and_cloud_rules(self):
        area=AreaDefinition('test','','',{'proj':'geos','lon_0':140.7,'h':35785863,'a':6378137,'b':6356752.3,'sweep':'y'},64,48,(-5000000,-5000000,5000000,5000000))
        rng=np.random.default_rng(34)
        for dtype,night_dtype in [(np.float32,np.float32),(np.float64,np.float64),(np.float64,np.float32)]:
            def data(values,name):
                return xr.DataArray(da.from_array(values.astype(dtype),chunks=(12,16)),dims=('y','x'),
                    coords={'x':np.arange(64),'y':np.arange(48)},attrs={'area':area,'name':name,'sensor':'ahi'})
            ir=data(rng.uniform(180,330,(48,64)),'IR');ir.data=da.where(da.indices((48,64))[0]==3,np.nan,ir.data)
            btd=data(rng.uniform(-3,8,(48,64)),'BTD');btd.data=da.where(da.indices((48,64))[0]==6,np.nan,btd.data)
            mask=data(rng.choice([0.,100.,50.,np.nan],(48,64)),'MASK')
            bg=xr.DataArray(da.from_array(rng.uniform(0,255,(3,48,64)).astype(night_dtype),chunks=(3,12,16)),dims=('bands','y','x'),
                coords={'bands':['R','G','B'],'x':np.arange(64),'y':np.arange(48)},
                attrs={'area':area,'name':'_night_background_hires','standard_name':'night_background','mode':'RGB','sensor':None})
            low=LowCloudCompositor('geo_color_low_clouds',standard_name='geo_color_low_clouds',values_land=100)([btd,ir,mask])
            high=HighCloudCompositor('geo_color_high_clouds',standard_name='geo_color_high_clouds')([ir])
            merged=BackgroundCompositor('geo_color_background_with_low_clouds',standard_name='night_ir_with_background')([low,bg])
            reference=BackgroundCompositor('geo_color_night',standard_name='night_ir_with_background')([high,merged]).compute()
            with patch.dict('os.environ',{'EARTHSTUDIO_H9_CUDA_CLOUDS':'2'}):
                actual=CudaNightBackgroundCompositor('geo_color_night',standard_name='night_ir_with_background')([high,merged],optional_datasets=[ir,btd,mask,bg]).compute()
            np.testing.assert_allclose(actual.values,reference.values,rtol=0,atol=np.finfo(dtype).eps*16,equal_nan=True)
            self.assertTrue(np.array_equal(np.isnan(actual.values),np.isnan(reference.values)))
            if dtype==np.float64 and night_dtype==np.float32:
                # Actual HSD/native-night precision combination: exact equality
                # catches pre-promotion enhancement rounding and byte ties.
                np.testing.assert_array_equal(actual.values,reference.values)

if __name__=='__main__':unittest.main()
