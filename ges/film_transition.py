"""Separate static ground lighting from measured VIS/IR cloud cross-fading.

This is a declared GeoColor-style display, not reconstructed true-color imagery,
surface reflectance, cloud optical depth, or a new cloud classification.
"""
from pathlib import Path
import json,warnings,hashlib
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from .catalog import utc_time
from .solar import solar_weights
from .download import read_manifest
from .render import create_satpy_scene,mask_goes_ir_quality,observation_interval
from .geosampling import inverse_global
from .blend import view_weight,edge_weight
from .blend_night import linear_rgb,encode_rgb

CLOUD_CLASSES=(2,3,5,6,7,8,9)
MASK_CLASSES=(1,*CLOUD_CLASSES)


def smoother(value,low,high):
    t=np.clip((np.asarray(value)-low)/(high-low),0,1)
    return np.clip(t**3*(t*(6*t-15)+10),0,1)


def vis_cloud_alpha(reflectance,classes,elevation_start,elevation_end):
    r,c,first,last=np.broadcast_arrays(reflectance,classes,elevation_start,elevation_end)
    coverage=np.isfinite(r)&np.isin(c,MASK_CLASSES)&(first>0)&(last>0)
    cosine=np.maximum(np.sin(np.deg2rad((first+last)/2)),np.sin(np.deg2rad(6)))
    measured=np.maximum(np.where(coverage,r,0)/cosine,0)
    # GeoColor VIS scaling 0..120% reflectance; no weak-cloud brightness boost.
    alpha=np.clip(measured/1.2,0,1)*np.isin(c,CLOUD_CLASSES)*coverage
    return alpha.astype(np.float32),coverage


def render_vis_cloud(record,out_dir,width=8192,vis_manifest=None):
    old=Path(record['image']);m=json.loads(old.with_suffix('.json').read_text())
    raw=read_manifest(Path(m['source_ir_manifest']));sat=raw['satellite']
    if sat.startswith('himawari'):band='B03';wave=.64
    elif sat.startswith('goes'):band='C02';wave=.64
    elif sat.startswith('meteosat_'):band='VIS006';wave=.635
    else:raise ValueError('No verified cached VIS band for this platform')
    visraw=read_manifest(Path(vis_manifest)) if vis_manifest else raw
    scene=create_satpy_scene(list(dict.fromkeys(raw['local_files']+visraw['local_files'])),sat);scene.load([band]);attrs=scene[band].attrs
    irband='B13' if sat.startswith('himawari') else 'C13' if sat.startswith('goes') else 'IR_108';scene.load([irband])
    if sat.startswith('himawari'):
        if attrs['area'].crs!=scene[irband].attrs['area'].crs or not np.allclose(attrs['area'].area_extent,scene[irband].attrs['area'].area_extent,atol=.01):
            raise ValueError('AHI500m VIS / 2km IR projected footprint differs')
    elif attrs['area']!=scene[irband].attrs['area']:raise ValueError('VIS and IR source native grids differ')
    interval=observation_interval(attrs)
    if attrs.get('units')!='%' or abs(attrs['wavelength'].central-wave)>.03:
        raise ValueError('Measured calibrated visible reflectance percent required')
    if sat.startswith('himawari'):
        if max(abs((utc_time(interval[j])-utc_time(m[['scan_start_utc','scan_end_utc'][j]])).total_seconds()) for j in [0,1])>1:
            raise ValueError('AHI VIS outside verified one-second detector union')
    elif interval!=(m['scan_start_utc'],m['scan_end_utc']):raise ValueError('VIS and verified source scan differ')
    quality=mask_goes_ir_quality(scene,raw['local_files'],band) if sat.startswith('goes') else 'Satpy native reader calibrated valid VIS samples; existing L2 cloud mask evidence'
    if m['width']!=width:raise ValueError('Existing verified class grid width required')
    classes=np.asarray(Image.open(old.parent/m['cloud_evidence_classes']))
    refl=inverse_global(attrs['area'],[np.ma.filled(scene[band].compute().values,np.nan)/100],width)[0]
    if classes.shape!=refl.shape:raise ValueError('Class/navigation grid mismatch')
    result=np.zeros(refl.shape,dtype=np.uint8);coverage=np.zeros_like(result)
    lon=-180+(np.arange(width)+.5)*360/width
    for row in range(0,width//2,128):
        sl=slice(row,min(row+128,width//2));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
        first=solar_weights(utc_time(interval[0]),lon[None,:],lat[:,None]).elevation_deg
        last=solar_weights(utc_time(interval[1]),lon[None,:],lat[:,None]).elevation_deg
        alpha,cov=vis_cloud_alpha(refl[sl],classes[sl],first,last)
        result[sl]=np.rint(alpha*255).astype(np.uint8);coverage[sl]=cov.astype(np.uint8)*255
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True);p=out_dir/(sat+'_vis_alpha.png')
    Image.fromarray(result).save(p);covpath=p.with_name(p.stem+'_coverage.png');Image.fromarray(coverage).save(covpath)
    p.with_suffix('.json').write_text(json.dumps({'product':'measured-visible-cloud-display','satellite':sat,
        'scan_start_utc':interval[0],'scan_end_utc':interval[1],'band':band,'input_units':'measured reflectance factor fraction',
        'source_manifest':str(Path(vis_manifest or m['source_ir_manifest']).resolve()),'class_image':str((old.parent/m['cloud_evidence_classes']).resolve()),
        'source_ir_metadata':m,'quality_policy':quality,'geometry':record['geometry'],'width':width,'height':width//2,
        'coverage':covpath.name,'cloud_pixels':int((result>0).sum()),'eligible_pixels':int((coverage>0).sum()),
        'display_mapping':'GeoColor NVIS: alpha=clip(nonnegative solar-normalized VIS/1.2,0,1); only original cloudy L2 classes; not optical depth',
        'limitations':'Achromatic measured VIS cloud texture on static ground; not measured RGB, no sharpening/Rayleigh retrieval. Original mask uncertainty and source resolution retained. Unknown mask uses IR fallback.'},indent=2),encoding='utf-8')
    return p


def daylight_display(alpha,ground,profile):
    """Display-only midtone lift; preserve measured support, black and white."""
    if profile=='legacy':return alpha,linear_rgb(ground)
    if profile!='sunlit-v1':raise ValueError('Unknown daylight display profile')
    # Hue-preserving exposure with a white-preserving shoulder. Never add a
    # uniform fog floor, normalize individual satellites, or change masks.
    linear=linear_rgb(ground);peak=np.max(linear,axis=-1,keepdims=True)
    lifted=linear*2.1/(1+1.1*peak)
    # Bounded monotonic display contrast, not a cloud optical-depth retrieval.
    # Finite gain at zero avoids promoting tiny VIS noise into an opaque veil.
    return alpha+.65*alpha*(1-alpha),lifted


def cloud_day_weight(elevation,profile='legacy'):
    if profile=='legacy':return smoother(elevation,0,24).astype(np.float32)
    if profile=='solar-sine-c2':
        # GeoColor day-side bounds sin(elevation)=0.1..0.3, C2 endpoints.
        return smoother(np.sin(np.deg2rad(elevation)),.1,.3).astype(np.float32)
    raise ValueError('Unknown solar cloud profile')


def layered_pixels(day_alpha,day_coverage,night_cloud,ir_coverage,day_ground,night_ground,elevation,confidence=1,daylight_profile='legacy',solar_profile='legacy'):
    """Continuous independent ground and cloud weights; return source attribution."""
    a=np.asarray(day_alpha,dtype=np.float32);cov=np.asarray(day_coverage,dtype=bool)
    ircov=np.asarray(ir_coverage,dtype=bool);night=np.asarray(night_cloud)
    elev=np.asarray(elevation);confidence=np.asarray(confidence)
    if not np.isfinite(a).all() or ((a<0)|(a>1)).any():raise ValueError('Finite VIS display alpha in 0..1 required')
    if not np.isfinite(confidence).all() or ((confidence<0)|(confidence>1)).any():raise ValueError('Finite source confidence in 0..1 required')
    a,daylinear=daylight_display(a,day_ground,daylight_profile)
    sw=smoother(elev,-12,24).astype(np.float32)
    cw=cloud_day_weight(elev,solar_profile)*cov*confidence
    iw=(1-cw)*ircov;availability=cw+iw
    # No static reference is allowed to create coverage over missing observations.
    na=night[...,3].astype(np.float32)/255
    opacity=a*cw+na*iw
    premult=a[...,None]*cw[...,None]+linear_rgb(night[...,:3])*(na*iw)[...,None]
    ground=daylinear*sw[...,None]+linear_rgb(night_ground)*(1-sw)[...,None]
    # Use one overlay convention on BOTH sides. The accepted night display is
    # an sRGB alpha-over; switching to linear-over only at -12deg creates a
    # visible jump even with a C2 solar curve. Interpolate cloud colors and
    # background illumination in linear RGB, then alpha-over in display sRGB.
    cloud_rgb=encode_rgb(np.divide(premult,opacity[...,None],out=np.zeros_like(premult),where=opacity[...,None]>0))
    cloud_alpha=np.divide(opacity,availability,out=np.zeros_like(opacity),where=availability>0)
    rgb=np.rint(cloud_rgb*cloud_alpha[...,None]+encode_rgb(ground)*(1-cloud_alpha[...,None])).astype(np.uint8)
    result=np.dstack([rgb,np.rint(availability*255).astype(np.uint8)])
    # Match the accepted legacy night compositing exactly when fully selected.
    deep=(elev<=-12)&ircov
    oldflat=np.rint(night[...,:3]*na[...,None]+night_ground*(1-na[...,None])).astype(np.uint8)
    result[deep,:3]=oldflat[deep];result[deep,3]=255
    result[availability==0]=0
    return result,cw,iw,sw


def load_reference(path,width,kind):
    path=Path(path);meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if meta['kind']!=kind:raise ValueError('Unexpected static reference kind')
    with path.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=meta['sha256']:raise ValueError('Static reference hash mismatch')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',Image.DecompressionBombWarning)
        with Image.open(path) as im:
            if im.size!=(meta['width'],meta['height']):raise ValueError('Static dimensions mismatch')
            pixels=np.asarray(im.convert('RGB').resize((width,width//2),Image.Resampling.LANCZOS)).copy()
    return pixels,meta


def compose_layered(paths,night_path,day_reference,night_reference,out,reference_utc,daylight_profile='legacy'):
    paths=list(map(Path,paths));night_path=Path(night_path);out=Path(out);stamp=utc_time(reference_utc)
    nm=json.loads(night_path.with_suffix('.json').read_text());width=nm['width'];height=nm['height']
    if nm.get('product')!='ir-night-display' or not paths:raise ValueError('Measured cloud inputs required')
    if abs((utc_time(nm['reference_utc'])-stamp).total_seconds())>1200:raise ValueError('IR bundle >20min from reference')
    if any(s['provenance']['display_recipe']!='night-transition-supported-v2' for s in nm['sources']):
        raise ValueError('Verified neutral warm-cloud transition branch required')
    night=np.asarray(Image.open(night_path));ircov=np.asarray(Image.open(night_path.parent/nm['source_ir_coverage']))>0
    dayground,dm=load_reference(day_reference,width,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    nightground,lm=load_reference(night_reference,width,'static reference night-lights composite, not contemporaneous with satellite clouds')
    nightground=np.maximum(nightground,(4,5,12)).astype(np.uint8)
    numerator=np.zeros((height,width),np.float32);den=np.zeros_like(numerator);best=np.zeros_like(den);source=np.zeros_like(den,np.uint8);records=[]
    lon=-180+(np.arange(width)+.5)*360/width
    for index,p in enumerate(paths,1):
        m=json.loads(p.with_suffix('.json').read_text());a=np.asarray(Image.open(p),np.float32)/255
        cov=np.asarray(Image.open(p.parent/m['coverage']))>0
        if m['product']!='measured-visible-cloud-display' or a.shape!=(height,width):raise ValueError('Verified matching VIS grid required')
        if abs((utc_time(m['scan_start_utc'])-stamp).total_seconds())>1200:raise ValueError('VIS source >20min from reference')
        weights=edge_weight(cov,16)
        for row in range(0,height,128):
            sl=slice(row,min(row+128,height));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
            weights[sl]*=view_weight(lon[None,:],lat[:,None],m['geometry'])
        weights[~cov]=0;numerator+=a*weights;den+=weights
        wins=weights>best;best[wins]=weights[wins];source[wins]=index
        records.append({'image':str(p.resolve()),'provenance':m})
    daycov=den>0;dayalpha=np.divide(numerator,den,out=np.zeros_like(den),where=daycov)
    confidence=smoother(distance_transform_edt(daycov),0,32).astype(np.float32)
    rgba=np.zeros_like(night);daymap=np.zeros_like(source);irmap=np.zeros_like(source);groundmap=np.zeros_like(source);gap=np.zeros_like(source)
    for row in range(0,height,128):
        sl=slice(row,min(row+128,height));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/width
        elev=solar_weights(stamp,lon[None,:],lat[:,None]).elevation_deg
        rgba[sl],dw,iw,sw=layered_pixels(dayalpha[sl],daycov[sl],night[sl],ircov[sl],dayground[sl],nightground[sl],elev,confidence[sl],daylight_profile)
        daymap[sl]=np.rint(dw*255).astype(np.uint8);irmap[sl]=np.rint(iw*255).astype(np.uint8);groundmap[sl]=np.rint(sw*255).astype(np.uint8)
        gap[sl]=((elev>0)&~daycov[sl]&ircov[sl]).astype(np.uint8)*255
    out.parent.mkdir(parents=True,exist_ok=True);Image.fromarray(rgba).save(out)
    for label,values in [('day_contribution',daymap),('night_contribution',irmap),('surface_day_weight',groundmap),('measured_ir_day_gap',gap),('visible_source',source),
                         ('observed_vis_alpha',np.rint(dayalpha*255).astype(np.uint8)),('observed_vis_coverage',daycov.astype(np.uint8)*255)]:
        Image.fromarray(values).save(out.with_name(out.stem+'_'+label+'.png'))
    metadata={'product':'day-night-display','display_recipe':'separate-ground-measured-vis-ir-c2-v4','width':width,'height':height,
        'daylight_profile':daylight_profile,
        'daylight_display_mapping':('Linear RGB ground exposure 2.1/(1+1.1*maxRGB); measured VIS display alpha a+0.65*a*(1-a); globally identical, display only, original cached alpha retained' if daylight_profile=='sunlit-v1' else 'Legacy ground and linear VIS display alpha'),
        'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'observed_utc':reference_utc,'reference_utc':reference_utc,
        'contains_surface_and_clouds':True,'alpha_meaning':'union of measured cloud-input coverage, NOT cloud optical depth',
        'day_sources':records,'night_source':nm,'night_image':str(night_path.resolve()),'day_static_ground':dm,'night_static_ground':lm,
        'surface_transition':'C2 smootherstep solar elevation -12..24deg; independent of satellite VIS availability',
        'cloud_transition':'C2 smootherstep solar elevation 0..24deg; measured VIS on actual supported cloud classes; complementary measured IR; inward32px VIS support feather',
        'overlay_convention':'Linear RGB interpolation within cloud/background layers, then consistent sRGB alpha-over at every solar angle, matching accepted night rendering without a compositing-space cutoff',
        'day_ground_is_contemporaneous':False,'day_clouds_are_measured':True,'is_true_color_rgb':False,
        'limitations':'2004-10 static ground, 2016 static night reference. Actual achromatic cloud VIS from the explicitly listed day_sources; not recovered full-color 2020 surface. L2 masks can miss/misclassify clouds. No new polar observations, no cloud height/volume, scan times/parallax remain. Daylight VIS outside sources is explicitly IR fallback.'}
    out.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8');return out
