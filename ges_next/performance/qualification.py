"""Real CUDA threshold/NaN checks before admitting the existing stock-equation backend."""
import numpy as np

def qualify():
    from ges.earth_validation.cuda_clouds import low_block,high_block
    for dtype in (np.float32,np.float64):
        btd=np.array([[-1,0,np.nextafter(dtype(0),dtype(1)),2,4,np.nextafter(dtype(4),dtype(5)),np.nan,np.inf]],dtype=dtype)
        for win in (229.999,230,np.nan):
            for mask in (0,100,50,np.nan):
                alpha=np.where(btd<=0,1,np.where(btd>4,0,-.25*btd+1)).astype(dtype)
                lum=btd if mask in (0,100) else np.full_like(btd,np.nan)
                alpha=1-alpha if mask in (0,100) else np.full_like(btd,np.nan)
                if not win>=230:alpha=np.zeros_like(btd)
                actual=low_block(btd,np.full_like(btd,win),np.full_like(btd,mask),((100.,),(0.,),True,1.,0.,4.,0.,4.))
                np.testing.assert_array_equal(actual,np.stack((lum,alpha)))
        lat=np.array([[0,29.999,30,45,60,60.001,np.inf,np.nan]],dtype=dtype)
        value=np.array([[210,230,250,275,300,310,np.nan,260]],dtype=dtype)
        lo=np.where(lat<30,dtype(210),np.where(lat>60,dtype(230),dtype(20/30)*lat+dtype(190)))
        slope=dtype(1)/(lo-dtype(300));offset=dtype(1)-slope*lo
        alpha=np.where(value<=lo,dtype(1),np.where(value>300,dtype(0),slope*value+offset))
        np.testing.assert_array_equal(high_block(value,lat,((210.,230.),(30.,60.),300.,1.,False)),np.stack((value,alpha)))
    return True
