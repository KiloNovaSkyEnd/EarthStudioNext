"""ABI mask/phase/pressure alignment using delivered fixed-grid coordinates.

Pressure is a 10 km retrieval, nearest sampled for display, never a new 2 km
height retrieval. Its file does not deliver per-pixel pressure uncertainty.
"""
from pathlib import Path
import netCDF4
import numpy as np
from .catalog import utc_time


def nearest_axis(source,target):
    source=np.asarray(source,dtype=np.float64);target=np.asarray(target,dtype=np.float64)
    if source.ndim!=1 or target.ndim!=1 or len(source)<2 or not np.isfinite(source).all():
        raise ValueError('Finite 1D source coordinates required')
    reverse=source[1]<source[0];a=source[::-1] if reverse else source
    if not (np.diff(a)>0).all() or not np.allclose(np.diff(a),np.diff(a)[0],rtol=1e-3,atol=1e-9):
        raise ValueError('Uniform monotonic fixed-grid axis required')
    upper=np.clip(np.searchsorted(a,target),1,len(a)-1);lower=upper-1
    ix=np.where(abs(target-a[lower])<=abs(a[upper]-target),lower,upper)
    inside=np.isfinite(target)&(abs(target-a[ix])<=np.diff(a)[0]/2+1e-8)
    return (len(a)-1-ix if reverse else ix),inside


def abi_classes(mask,phase,pressure,mask_q,phase_q,pressure_q,height_q):
    fields=[np.asarray(v) for v in [mask,phase,pressure,mask_q,phase_q,pressure_q,height_q]]
    if any(v.shape!=fields[0].shape for v in fields):raise ValueError('Aligned ABI evidence grid required')
    mask,phase,p,mq,pq,cq,hq=fields
    goodmask=np.isin(mask,[0,1])&(mq==0)
    c=np.zeros(mask.shape,dtype=np.uint8);c[goodmask]=4
    c[goodmask&(mask==0)&(phase==0)]=1
    cloudy=goodmask&(mask==1);c[cloudy]=3
    good=cloudy&(pq==0)&(cq==0)&(hq==0)&np.isfinite(p)&(p>0)&(p<=1100)
    c[good&np.isin(phase,[1,2])&(p>680)]=8
    # No class 5: high pressure confidence interval cannot be checked here.
    return c


def load_abi_evidence(files,area,ir_start,ir_end,satellite):
    kinds={'ACMF':['BCM','DQF'],'ACTPF':['Phase','DQF'],
           'CTPF':['PRES','DQF'],'ACHAF':['DQF']}
    data={};axes={};intervals={};nav=[];projection=None
    for kind,variables in kinds.items():
        paths=[Path(p) for p in files if f'ABI-L2-{kind}-' in Path(p).name]
        if len(paths)!=1:raise ValueError('Exactly one ABI evidence file per product required')
        with netCDF4.Dataset(paths[0]) as d:
            if d.platform_ID!='G'+satellite.removeprefix('goes'):raise ValueError('ABI platform mismatch')
            start,end=utc_time(d.time_coverage_start),utc_time(d.time_coverage_end)
            if end<start or abs((start-utc_time(ir_start)).total_seconds())>1 or abs((end-utc_time(ir_end)).total_seconds())>2:
                raise ValueError('ABI L2 is not the same IR scan (1 s start / 2 s end guard)')
            intervals[kind]=[d.time_coverage_start,d.time_coverage_end]
            pr=d['goes_imager_projection']
            proj={k:pr.getncattr(k) for k in ['perspective_point_height','semi_major_axis','semi_minor_axis',
                  'latitude_of_projection_origin','longitude_of_projection_origin','sweep_angle_axis']}
            if projection is None:projection=proj
            if proj!=projection:raise ValueError('ABI evidence projection mismatch')
            h=proj['perspective_point_height'];x=np.asarray(d['x'][:],dtype=np.float64)*h;y=np.asarray(d['y'][:],dtype=np.float64)*h
            if d['x'].units!='rad' or d['y'].units!='rad':raise ValueError('ABI angular coordinates required')
            axes[kind]=(x,y)
            for name in variables:
                if name=='PRES' and d[name].units!='hPa':raise ValueError('Delivered pressure must be hPa')
                data[kind,name]=np.ma.filled(d[name][:].astype(np.float32),np.nan)
                if data[kind,name].shape!=(len(y),len(x)):raise ValueError('ABI array/coordinate dimensions differ')
    targetx,targety=area.get_proj_vectors()
    pd=area.crs.to_dict()
    pd['a']=area.crs.ellipsoid.semi_major_metre
    pd['b']=area.crs.ellipsoid.semi_minor_metre
    # PROJ omits the default zero latitude for the geostationary projection.
    if pd.get('proj')!='geos':raise ValueError('Actual geostationary projection required')
    pd['lat_0']=pd.get('lat_0',0)
    for key,value in [('h',projection['perspective_point_height']),('a',projection['semi_major_axis']),
                      ('b',projection['semi_minor_axis']),('lon_0',projection['longitude_of_projection_origin']),
                      ('lat_0',projection['latitude_of_projection_origin'])]:
        if not np.isclose(float(pd[key]),float(value),rtol=0,atol=.01):raise ValueError('ABI L2/L1 projection differs')
    if pd.get('sweep')!=projection['sweep_angle_axis']:raise ValueError('ABI projection sweep differs')
    for kind in ['ACMF','ACTPF']:
        x,y=axes[kind]
        if len(x)!=len(targetx) or len(y)!=len(targety):raise ValueError('ABI fine grids differ')
        delta=max(float(abs(x-targetx).max()),float(abs(y-targety).max()))
        # Delivered radian coordinates are decoded float32; Satpy constructs
        # uniform pixel centres. Real full-disk difference is <=0.857 m,
        # versus 2004 m pixel spacing. Keep a bounded one-metre tolerance.
        if delta>1:raise ValueError('ABI L2/L1 fine coordinate grids differ')
        nav.append({'product':kind,'max_projection_coordinate_difference_m':delta})
    coarse={}
    for kind in ['CTPF','ACHAF']:
        x,y=axes[kind];ix,vx=nearest_axis(x,targetx);iy,vy=nearest_axis(y,targety)
        valid=vy[:,None]&vx[None,:]
        for name in kinds[kind]:coarse[kind,name]=np.where(valid,data[kind,name][iy[:,None],ix[None,:]],np.nan)
        nav.append({'product':kind,'delivered_shape':list(data[kind,'DQF'].shape),
                    'mapping':'nearest delivered projection coordinate; no pressure interpolation',
                    'valid_target_pixels':int(valid.sum())})
    c=abi_classes(data['ACMF','BCM'],data['ACTPF','Phase'],coarse['CTPF','PRES'],
                  data['ACMF','DQF'],data['ACTPF','DQF'],coarse['CTPF','DQF'],coarse['ACHAF','DQF'])
    stats={'source_intervals_utc':intervals,'navigation_checks':nav,
           'native_grid_class_counts':{str(v):int((c==v).sum()) for v in np.unique(c)},
           'pressure_native_shape':list(data['CTPF','PRES'].shape),
           'pressure_uncertainty':'not supplied; NEVER substituted with zero',
           'quality_policy':'BCM=1, phase=1/2, all DQF=0, nominal delivered PRES>680 hPa; class 8, not AHI strict interval class',
           'pressure_mapping_resolution_warning':'10 km pressure nearest sampled on 2 km imagery; not a new 2 km cloud height retrieval'}
    return c,stats
