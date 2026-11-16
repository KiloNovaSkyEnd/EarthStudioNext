"""Real-source night navigation checks; independent coastline QA is separate."""
import json
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer
from pyresample import create_area_def
from .night_background import read_on_area
from .project import save


def verify(root,detail_metadata):
    root=Path(root)
    metadata=json.loads(Path(detail_metadata).read_text(encoding='utf-8'))
    height,width=metadata['shape']
    area=create_area_def('native_registration',metadata['crs_wkt'],shape=(height,width),area_extent=metadata['extent'],units='m')
    night=root/'raw/references/blackmarble_2016_500m/global_500m.vrt'
    warped=read_on_area(night,area)
    x,y=area.get_proj_vectors()
    forward=Transformer.from_crs(area.crs,'EPSG:4326',always_xy=True)
    inverse=Transformer.from_crs('EPSG:4326',area.crs,always_xy=True)
    rows=np.linspace(32,height-33,9,dtype=int); cols=np.linspace(32,width-33,9,dtype=int)
    records=[]
    with rasterio.open(night) as source:
        for row in rows:
            for col in cols:
                lon,lat=forward.transform(x[col],y[row]); xx,yy=inverse.transform(lon,lat)
                srcrow,srccol=source.index(lon,lat)
                expected=source.read(window=rasterio.windows.Window(srccol,srcrow,1,1))[:,0,0]
                actual=warped[:,row,col]
                records.append({'lon':float(lon),'lat':float(lat),'sensor_row':int(row),'sensor_col':int(col),
                    'original_night_pixel':[srcrow,srccol], 'rgb_equal':bool(np.array_equal(expected,actual)),
                    'roundtrip_metres':float(np.hypot(xx-x[col],yy-y[row]))})
    passed=all(r['rgb_equal'] and r['roundtrip_metres']<.01 for r in records)
    report={'checks':records,'navigation_roundtrip_and_nearest_samples_passed':passed,
        'source_year':2016,'source_nominal_resolution_m':500,'actual_500m_source_used':True,
        'independent_coastline_control_points_passed':False,'geographic_acceptance_passed':False,
        'limits':'81 real static-source samples verify projection, pixel centres and orientation. Does not independently prove satellite navigation/coastline accuracy or cloud parallax.'}
    save(root/'reports/night_registration.json',report)
    if not passed: raise ValueError('Real-source night background navigation check failed')
    return report
