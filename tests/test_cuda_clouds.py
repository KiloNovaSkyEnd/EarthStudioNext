"""Actual CUDA equality at stock production thresholds; no generated weather output."""
import unittest
import numpy as np
from ges.earth_validation.cuda_clouds import low_block,high_block

class CudaCloudTests(unittest.TestCase):
    def test_low_thresholds_nan_and_cold_window(self):
        for dtype in [np.float32,np.float64]:
            btd=np.array([[-1,0,np.nextafter(dtype(0),dtype(1)),2,4,np.nextafter(dtype(4),dtype(5)),np.nan,np.inf]],dtype=dtype)
            for win in [229.999,230,np.nan]:
                for mask in [0,100,50,np.nan]:
                    a=np.where(btd<=0,1,np.where(btd>4,0,-.25*btd+1)).astype(dtype)
                    lum=btd if mask in [0,100] else np.full_like(btd,np.nan)
                    alpha=1-a if mask in [0,100] else np.full_like(btd,np.nan)
                    alpha=alpha if win>=230 else np.zeros_like(btd)
                    actual=low_block(btd,np.full_like(btd,win),np.full_like(btd,mask),((100.,),(0.,),True,1.,0.,4.,0.,4.))
                    np.testing.assert_array_equal(actual,np.stack([lum,alpha]))
    def test_high_latitude_boundaries_and_missing_values(self):
        for dtype in [np.float32,np.float64]:
            lats=np.array([[0,29.999,30,45,60,60.001,np.inf,np.nan]],dtype=dtype)
            values=np.array([[210,230,250,275,300,310,np.nan,260]],dtype=dtype)
            lo=np.where(lats<30,dtype(210),np.where(lats>60,dtype(230),dtype(20/30)*lats+dtype(190)))
            slope=dtype(1)/(lo-dtype(300));offset=dtype(1)-slope*lo
            expected=np.where(values<=lo,dtype(1),np.where(values>300,dtype(0),slope*values+offset))
            actual=high_block(values,lats,((210.,230.),(30.,60.),300.,1.,False))
            np.testing.assert_array_equal(actual,np.stack([values,expected]))

if __name__=='__main__':unittest.main()
