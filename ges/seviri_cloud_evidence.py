"""Verified SEVIRI cloud mask + good-quality cloud top height display evidence.

CTH is delivered at 9 km. Height <3 km is an explicitly height-based display
selection, not an ISCCP pressure class or liquid-phase retrieval.
"""
from pathlib import Path
from datetime import timezone
import numpy as np
from satpy import Scene
from .catalog import utc_time


def area_from_points(native_area,shape,xy,longitudes,latitudes):
    """Fit delivered uniform geos centres, then check held-out navigation.

    Some legacy GRIB files scan NW->SE while the installed reader assumes SW
    orientation; its CTH extent also shifts a coarse pixel. Never flip data
    based on names alone: actual ecCodes geolocation determines coordinates.
    """
    from pyproj import Transformer
    xy=np.asarray(xy);lon=np.asarray(longitudes);lat=np.asarray(latitudes)
    transform=Transformer.from_crs('EPSG:4326',native_area.crs,always_xy=True)
    px,py=map(np.asarray,transform.transform(lon,lat))
    sx=(px[1]-px[0])/(xy[1,0]-xy[0,0]);sy=(py[3]-py[2])/(xy[3,1]-xy[2,1])
    x0=px[0]-xy[0,0]*sx;y0=py[2]-xy[2,1]*sy
    residual=max(float(abs(px-(x0+xy[:,0]*sx)).max()),float(abs(py-(y0+xy[:,1]*sy)).max()))
    if not np.isfinite([sx,sy,x0,y0,residual]).all() or sx<=0 or sy>=0 or residual>abs(sx)*.02:
        raise ValueError('GRIB delivered geolocation is not the expected uniform NW->SE geos grid')
    rows,cols=shape
    extent=(x0-sx/2,y0+(rows-.5)*sy,x0+(cols-.5)*sx,y0-sy/2)
    area=native_area.copy(area_extent=extent)
    check_lon,check_lat=area.get_lonlat_from_array_coordinates(xy[:,0],xy[:,1])
    error=max(float(abs((check_lon-lon+180)%360-180).max()),float(abs(check_lat-lat).max()))
    if error>.002:raise ValueError('Corrected GRIB geolocation residual exceeds 0.002 degrees')
    return area,{'max_geolocation_error_deg':error,'max_projection_residual_m':residual,
                 'x_step_m':float(sx),'y_step_m':float(sy),'sample_count':len(xy),
                 'area_extent':list(extent),'method':'Delivered ecCodes lon/lat fit; four construction samples plus three held-out samples; raw data order unchanged'}


def seviri_classes(mask,height,quality):
    mask,height,quality=[np.asarray(a) for a in [mask,height,quality]]
    if not mask.shape==height.shape==quality.shape:raise ValueError('Aligned SEVIRI evidence required')
    c=np.zeros(mask.shape,dtype=np.uint8)
    c[np.isin(mask,[0,1])]=1;c[mask==2]=3
    c[(mask==2)&(quality==0)&np.isfinite(height)&(height>0)&(height<3000)]=9
    return c


def load_seviri_evidence(files,area,ir_attrs,ir_start,ir_end):
    import eccodes as ec
    headers=[];native_shapes={};navigation_points={}
    for path in files:
        if not str(path).endswith('.grb'):raise ValueError('Documented SEVIRI GRIB inputs required')
        with open(path,'rb') as f:
            ec.codes_grib_multi_support_on()
            while True:
                g=ec.codes_grib_new_from_file(f)
                if g is None:break
                try:
                    h={k:ec.codes_get(g,k) for k in ['parameterNumber','dataDate','dataTime','Nx','Ny','units',
                                                        'longitudeOfSubSatellitePointInDegrees','bitmapPresent']}
                    if h['parameterNumber'] not in [2,3,7]:raise ValueError('Unexpected GRIB support parameter')
                    if h['parameterNumber']==2 and h['units']!='m':raise ValueError('Cloud top height must be metres')
                    from datetime import datetime,timedelta
                    start=datetime.strptime(str(h['dataDate'])+str(h['dataTime']).zfill(4),'%Y%m%d%H%M').replace(tzinfo=timezone.utc)
                    # Header time starts the nominal 15-minute repeat cycle;
                    # L1 provides the actual active scan inside that cycle.
                    if not (start<=utc_time(ir_start)<=utc_time(ir_end)<=start+timedelta(minutes=15)):
                        raise ValueError('L1 actual scan is outside L2 GRIB nominal repeat cycle')
                    lon=area.crs.to_dict()['lon_0']
                    if abs((float(h['longitudeOfSubSatellitePointInDegrees'])-lon+180)%360-180)>.01:
                        raise ValueError('SEVIRI L2/L1 sub-satellite longitude differs')
                    native_shapes[str(h['parameterNumber'])]=[h['Ny'],h['Nx']]
                    n=h['Nx'];xy=np.array([[n//4,n//2],[3*n//4,n//2],[n//2,n//4],[n//2,3*n//4],
                                          [int(n*.35),int(n*.4)],[int(n*.55),int(n*.4)],[int(n*.4),int(n*.65)]])
                    indices=(xy[:,1]*n+xy[:,0]).tolist()
                    navigation_points[h['parameterNumber']]=(xy,ec.codes_get_double_elements(g,'longitudes',indices),
                                                                ec.codes_get_double_elements(g,'latitudes',indices))
                    headers.append({'file':Path(path).name,**h})
                finally:ec.codes_release(g)
    if sorted(h['parameterNumber'] for h in headers)!=[2,3,7]:raise ValueError('Exactly mask/height/quality fields required')
    l2=Scene(filenames=[str(p) for p in files],reader='seviri_l2_grib')
    names=['cloud_mask','cloud_top_height','cloud_top_quality'];l2.load(names)
    navigation=[]
    for name,param in zip(names,[7,2,3]):
        if l2[name].attrs.get('platform_name')!=ir_attrs.get('platform_name'):
            raise ValueError('SEVIRI L2/L1 platform differs')
        corrected,check=area_from_points(l2[name].attrs['area'],l2[name].shape,*navigation_points[param])
        l2[name].attrs['area']=corrected;navigation.append({'field':name,**check})
    mapped=l2.resample(area,resampler='nearest',reduce_data=False,radius_of_influence=15000)
    import dask
    mask,height,quality=dask.compute(*[mapped[n].data for n in names])
    classes=seviri_classes(mask,height,quality)
    return classes,{'grib_headers':headers,'native_shapes':native_shapes,
                    'navigation_checks':navigation,
                    'quality_policy':'CLM=2 cloudy, CTH quality=0 good, finite 0<cloud_top_height<3000 m',
                    'cloud_phase':'not delivered; class 9 is low cloud-top evidence, NOT liquid-phase classification',
                    'height_uncertainty':'not delivered; not substituted with zero',
                    'alignment':'geographic nearest using delivered GRIB area; 9 km height mapped onto 3 km IR, no new fine height retrieval',
                    'height_vs_pressure':'3 km display cutoff is not asserted identical to 680 hPa pressure cutoff',
                    'native_grid_class_counts':{str(v):int((classes==v).sum()) for v in np.unique(classes)}}
