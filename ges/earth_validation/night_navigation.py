"""Exact pixel-centre nearest navigation, with bounded geographic source reads."""
import numpy as np
from pyproj import Transformer
from rasterio.windows import Window


def sample(source,area,out=None):
    if source.crs.to_epsg()!=4326 or source.transform.b or source.transform.d:
        raise ValueError('Static night navigation requires the verified north-up geographic source')
    x,y=area.get_proj_vectors()
    inverse=~source.transform
    projection=Transformer.from_crs(area.crs,source.crs,always_xy=True)
    output=out if out is not None else np.empty((3,area.height,area.width),np.float32)
    output[:]=np.nan
    for start in range(0,area.height,64):
        end=min(area.height,start+64)
        xx,yy=np.meshgrid(x,y[start:end]); lon,lat=projection.transform(xx,yy)
        col,row=inverse*(lon,lat)
        valid=np.isfinite(col)&np.isfinite(row)&(col>=0)&(row>=0)&(col<source.width)&(row<source.height)
        ci=np.zeros(col.shape,np.int64); ri=np.zeros(row.shape,np.int64)
        ci[valid]=np.floor(col[valid]).astype(np.int64); ri[valid]=np.floor(row[valid]).astype(np.int64)
        stripe=ri//128
        block=output[:,start:end]
        for number in np.unique(stripe[valid]):
            selected=valid&(stripe==number)
            columns=ci[selected]; rows=ri[selected]
            c0=int(columns.min()); c1=int(columns.max())+1
            r0=int(rows.min()); r1=int(rows.max())+1
            # At most 128 geographic rows; never materialize global RGB.
            pixels=source.read([1,2,3],window=Window(c0,r0,c1-c0,r1-r0))
            block[:,selected]=pixels[:,rows-r0,columns-c0]
    return output
