"""Observed-overlap night display mixing in linear premultiplied color.

Not a radiometric or categorical retrieval fusion. Never fills missing coverage.
"""
import json
from pathlib import Path
import warnings
import numpy as np
from PIL import Image
from .blend import edge_weight,view_weight,view_cosine
from .catalog import utc_time
from .solar import solar_weights


def linear_rgb(rgb):
    x=np.asarray(rgb,dtype=np.float32)/255
    return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)


def encode_rgb(rgb):
    x=np.clip(rgb,0,1)
    return np.rint(np.where(x<=.0031308,12.92*x,1.055*x**(1/2.4)-.055)*255).astype(np.uint8)


def mix_pixels(pixels,weights):
    """Small-array reference kernel used in actual streaming fusion and tests."""
    if len(pixels)!=len(weights) or not pixels:raise ValueError('Matching nonempty source lists required')
    shape=np.asarray(pixels[0]).shape
    if shape[-1]!=4:raise ValueError('RGBA required')
    premult=np.zeros(shape[:-1]+(3,),dtype=np.float32);alpha=np.zeros(shape[:-1],dtype=np.float32);den=np.zeros_like(alpha)
    for image,weight in zip(pixels,weights):
        image=np.asarray(image);weight=np.asarray(weight,dtype=np.float32)
        if image.shape!=shape or weight.shape!=shape[:-1] or not np.isfinite(weight).all() or (weight<0).any():
            raise ValueError('Matching finite nonnegative weight arrays required')
        a=image[...,3].astype(np.float32)/255
        premult+=linear_rgb(image[...,:3])*(a*weight)[...,None];alpha+=a*weight;den+=weight
    color=np.divide(premult,alpha[...,None],out=np.zeros_like(premult),where=alpha[...,None]>0)
    a=np.divide(alpha,den,out=np.zeros_like(alpha),where=den>0)
    return np.dstack([encode_rgb(color),np.rint(a*255).astype(np.uint8)])


def grazing_alpha(pixels,longitude,latitude,geometry):
    """Global-preview alpha guard only; never a source quality/coverage flag."""
    t=np.clip((view_cosine(longitude,latitude,geometry)-.15)/.10,0,1)
    fade=(t*t*(3-2*t)).astype(np.float32)
    result=np.asarray(pixels).copy()
    result[...,3]=np.rint(result[...,3].astype(np.float32)*fade).astype(np.uint8)
    return result


def blend_night(records,lights,out,reference_utc,feather=64,grazing_guard=False):
    out=Path(out);stamp=utc_time(reference_utc)
    if not records or len(records)>255 or out.suffix.lower()!='.png':raise ValueError('Sources and PNG output required')
    if any(Path(r['image']).resolve()==out.resolve() for r in records):raise ValueError('Cannot overwrite input')
    inputs=[];coverages=[];weights=[];sources=[];grid=None
    for record in records:
        path=Path(record['image']);m=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if str(m.get('validation_status','')).startswith('REJECTED'):raise ValueError('Source failed navigation validation')
        current=(m['width'],m['height'])
        if (m.get('product')!='ir-night-display' or m.get('projection')!='EPSG:4326' or
            m.get('extent_wsen')!=[-180,-90,180,90] or current[0]!=2*current[1] or
            (grid is not None and current!=grid) or
            m.get('display_recipe') not in ['cloud-evidence-shared-transfer-v5','cloud-evidence-supported-visibility-v6','cloud-evidence-signed-texture-v8','night-transition-supported-v1','night-transition-supported-v2','night-multispectral-experimental-v1']):
            raise ValueError('Matching documented input night-display grids required')
        if m['display_recipe']=='night-multispectral-experimental-v1':
            if len(m['sources'])!=1:raise ValueError('One sensor footprint per geometry record required')
            start=utc_time(m['sources'][0]['scan_start_utc']);end=utc_time(m['sources'][0]['scan_end_utc'])
        else:
            start=utc_time(m['scan_start_utc']);end=utc_time(m['scan_end_utc'])
        if end<start or abs((start-stamp).total_seconds())>1200:raise ValueError('Source reversed or >20 minutes from reference')
        with Image.open(path) as im:
            if im.mode!='RGBA' or im.size!=current:raise ValueError('Input texture metadata mismatch')
            pixels=np.asarray(im)
        with Image.open(path.parent/m['source_ir_coverage']) as im:
            if im.mode!='L' or im.size!=current:raise ValueError('Coverage metadata mismatch')
            coverage=np.asarray(im)
        if not np.isin(coverage,[0,255]).all() or pixels[...,3][coverage==0].any():raise ValueError('Actual binary IR coverage required')
        grid=current;mask=coverage>0;weight=edge_weight(mask,feather)
        if grazing_guard:pixels=pixels.copy()
        lon=-180+(np.arange(grid[0])+.5)*360/grid[0]
        for row in range(0,grid[1],128):
            sl=slice(row,min(row+128,grid[1]));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/grid[0]
            weight[sl]*=view_weight(lon[None,:],lat[:,None],record['geometry'])
            if grazing_guard:pixels[sl]=grazing_alpha(pixels[sl],lon[None,:],lat[:,None],record['geometry'])
        weight[~mask]=0
        inputs.append(pixels);coverages.append(mask);weights.append(weight)
        sources.append({**record,'provenance':m,'start_offset_seconds':(start-stamp).total_seconds()})
    shape=(grid[1],grid[0]);union=np.logical_or.reduce(coverages)
    count=np.sum(coverages,axis=0,dtype=np.uint8);dominant=np.argmax(weights,axis=0).astype(np.uint8)+1;dominant[~union]=0
    result=np.zeros(shape+(4,),dtype=np.uint8)
    for row in range(0,shape[0],128):
        sl=slice(row,min(row+128,shape[0]));result[sl]=mix_pixels([p[sl] for p in inputs],[w[sl] for w in weights])
        # Preserve single-source observations, including transparent RGB bytes.
        for p,mask in zip(inputs,coverages):
            only=mask[sl]&(count[sl]==1);result[sl][only]=p[sl][only]
    assert not result[...,3][~union].any()
    lights=Path(lights);ref=json.loads(lights.with_suffix('.json').read_text(encoding='utf-8'))
    if ref.get('kind')!='static reference night-lights composite, not contemporaneous with satellite clouds':raise ValueError('Static light provenance required')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',Image.DecompressionBombWarning)
        with Image.open(lights) as im:
            if im.size!=(ref['width'],ref['height']):raise ValueError('Static light dimensions mismatch')
            surface=np.asarray(im.convert('RGB').resize(grid,Image.Resampling.LANCZOS)).copy()
    for row in range(0,shape[0],128):
        sl=slice(row,min(row+128,shape[0]));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/grid[0]
        solar=solar_weights(stamp,lon[None,:],lat[:,None])
        surface[sl]=np.maximum(np.rint(surface[sl]*solar.city_lights[...,None]).astype(np.uint8),(4,5,12))
    surface[~union]=(24,11,35)
    out.parent.mkdir(parents=True,exist_ok=True)
    surface_path=out.with_name(out.stem+'_surface.png');coverage_path=out.with_name(out.stem+'_coverage.png')
    Image.fromarray(result).save(out);Image.fromarray(surface).save(surface_path)
    Image.fromarray(union.astype(np.uint8)*255).save(coverage_path)
    Image.fromarray(count).save(out.with_name(out.stem+'_observation_count.png'))
    Image.fromarray(dominant).save(out.with_name(out.stem+'_dominant_source.png'))
    metadata={'product':'ir-night-display','display_recipe':'linear-premultiplied-observed-night-blend-v1',
              'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':grid[0],'height':grid[1],
              'reference_utc':reference_utc,'observed_utc':reference_utc,'sources':sources,
              'source_ir_coverage':coverage_path.name,'night_surface':surface_path.name,
              'observed_pixels':int(union.sum()),'is_single_sensor_observation':False,
              'is_categorical_fusion':False,'is_gap_filled':False,'feather_grid_pixels':feather,
              'color_mixing':'decode sRGB; normalized view/edge weights; premultiply linear color by alpha; mix; unpremultiply; encode sRGB',
              'grazing_display_guard':{'enabled':bool(grazing_guard),'zero_at_or_below_view_cosine':.15,'full_at_or_above_view_cosine':.25,'effect':'source alpha only before mixing; RGB/native coverage unchanged; display choice, NOT delivered quality flag; spherical source geometry approximation'},
              'limitations':'Derived multi-time display only; differing scan times, parallax, spectral responses and confidence remain. '
                            'No recovered polar coverage, cloud-type truth or full daylight RGB composition. '
                            'Source pressure-based and height-based classes/uncertainties remain separate; same palette is not identical classification evidence.'}
    out.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    surface_path.with_suffix('.json').write_text(json.dumps({'kind':'static night reference with computed solar gating and missing-IR tint',
        'source_reference':ref,'model_utc':reference_utc,'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],
        'width':grid[0],'height':grid[1],'is_contemporaneous_observation':False},indent=2),encoding='utf-8')
    return out
