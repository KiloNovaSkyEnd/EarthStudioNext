"""Inverse navigation to an actual geostationary image pixel footprint.

Unlike geographic KD-tree radius searches, a target is assigned only to its
containing native projected pixel. Invalid native samples never borrow nearby
valid values. No estimated observations or cross-limb extrapolation.
"""
import numpy as np


def native_indices(area,longitude,latitude):
    operation=area.crs.coordinate_operation
    if operation is None or not operation.method_name.startswith('Geostationary Satellite'):
        raise ValueError('Verified geostationary source area required')
    lon,lat=np.broadcast_arrays(np.asarray(longitude,dtype=np.float64),np.asarray(latitude,dtype=np.float64))
    x,y=area.get_array_coordinates_from_lonlat(lon,lat)
    x=np.ma.filled(x,np.nan);y=np.ma.filled(y,np.nan)
    valid=np.isfinite(lon)&np.isfinite(lat)&(np.abs(lat)<=90)&np.isfinite(x)&np.isfinite(y)
    ix=np.floor(np.where(valid,x,-2)+.5).astype(np.int64)
    iy=np.floor(np.where(valid,y,-2)+.5).astype(np.int64)
    valid&=(ix>=0)&(ix<area.width)&(iy>=0)&(iy<area.height)
    return ix,iy,valid


def sample_native(area,arrays,longitude,latitude):
    values=[np.ma.filled(np.ma.asarray(a,dtype=np.float32),np.nan)
            if np.ma.isMaskedArray(a) else np.asarray(a) for a in arrays]
    if not values or any(a.shape!=area.shape for a in values):
        raise ValueError('All native arrays must match the actual source area')
    ix,iy,valid=native_indices(area,longitude,latitude)
    result=[]
    for a in values:
        out=np.full(valid.shape,np.nan,dtype=np.float32)
        out[valid]=a[iy[valid],ix[valid]]
        result.append(out)
    return result


def inverse_global(area,arrays,width):
    if not isinstance(width,int) or width<512 or width>8192 or width%2:
        raise ValueError('Even global width in 512..8192 required')
    result=[np.full((width//2,width),np.nan,dtype=np.float32) for _ in arrays]
    lon=-180+(np.arange(width)+.5)*360/width
    for row in range(0,width//2,128):
        sl=slice(row,min(row+128,width//2));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
        mapped=sample_native(area,arrays,lon[None,:],lat[:,None])
        for target,data in zip(result,mapped):target[sl]=data
    return result


def limb_visibility(area,longitude,latitude):
    """Display fade at grazing view angles; never an observed-coverage mask.

    Use actual geos ellipsoid/height and geodetic surface normal. Fade only
    cos(view zenith)<0.08 (~85.4 deg); all more central pixels exactly one.
    """
    operation=area.crs.coordinate_operation
    if operation is None or not operation.method_name.startswith('Geostationary Satellite'):
        raise ValueError('Geostationary area required')
    p={v.name:v for v in operation.params};ellipsoid=area.crs.ellipsoid
    a=ellipsoid.semi_major_metre;b=ellipsoid.semi_minor_metre
    if p['Satellite Height'].unit_name!='metre' or p['Longitude of natural origin'].unit_name!='degree':
        raise ValueError('Verified metre/degree source projection required')
    h=float(p['Satellite Height'].value);lon0=np.deg2rad(float(p['Longitude of natural origin'].value))
    lon,lat=np.broadcast_arrays(np.deg2rad(np.asarray(longitude)),np.deg2rad(np.asarray(latitude)))
    e2=1-(b/a)**2;n=a/np.sqrt(1-e2*np.sin(lat)**2)
    x=n*np.cos(lat)*np.cos(lon);y=n*np.cos(lat)*np.sin(lon);z=n*(1-e2)*np.sin(lat)
    dx=(a+h)*np.cos(lon0)-x;dy=(a+h)*np.sin(lon0)-y;dz=-z
    cosine=(dx*np.cos(lat)*np.cos(lon)+dy*np.cos(lat)*np.sin(lon)+dz*np.sin(lat))/np.sqrt(dx*dx+dy*dy+dz*dz)
    t=np.clip(np.where(np.isfinite(cosine),cosine,0)/.08,0,1)
    return (t*t*(3-2*t)).astype(np.float32)
