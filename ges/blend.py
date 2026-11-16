"""Smooth display mixing of actual overlapping IR observations.

This derived display is not a calibrated single-sensor brightness temperature
product. Different scan times and spectral responses remain. No gap filling.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from .catalog import utc_time
from .render import IR_GRAY_RECIPE


def view_cosine(longitude,latitude,geometry):
    """Approximate spherical surface viewing cosine from source geometry."""
    lon,lat=np.broadcast_arrays(np.asarray(longitude,dtype=np.float64),np.asarray(latitude,dtype=np.float64))
    slon,slat=np.deg2rad([geometry['longitude'],geometry.get('latitude',0)])
    radius=float(geometry['earth_radius_m']); altitude=float(geometry['altitude_m'])
    if not np.isfinite([slon,slat,radius,altitude]).all() or radius<=0 or altitude<=0:
        raise ValueError('Finite actual projection geometry with positive radii required')
    central=np.sin(np.deg2rad(lat))*np.sin(slat)+np.cos(np.deg2rad(lat))*np.cos(slat)*np.cos(np.deg2rad(lon)-slon)
    ratio=1+altitude/radius
    cosine=(ratio*central-1)/np.sqrt(ratio*ratio+1-2*ratio*central)
    return cosine


def view_weight(longitude,latitude,geometry):
    """Fourth-power display weight; tiny floor retains near-limb observations."""
    return (np.maximum(view_cosine(longitude,latitude,geometry),0)+.001).astype(np.float32)**4


def edge_weight(mask,feather):
    if not isinstance(feather,int) or feather<1 or feather>256:
        raise ValueError('Feather width must be 1..256 grid pixels')
    # Longitudes wrap at the date line; polar rows do not wrap.
    padded=np.pad(np.pad(mask,((0,0),(feather,feather)),mode='wrap'),((1,1),(0,0)))
    distance=distance_transform_edt(padded)[1:-1,feather:-feather]
    return (np.minimum(distance/feather,1)**2).astype(np.float32)


def blend_ir(records,out,reference_utc,feather=64):
    """View/coverage-edge weighted grayscale display; input raw grids preserved."""
    out=Path(out); reference_utc=utc_time(reference_utc)
    if not records or len(records)>255 or out.suffix.lower()!='.png':
        raise ValueError('Provide 1..255 source records and a PNG output')
    auxiliary=[out.with_name(out.stem+s+'.png') for s in ['_dominant_source','_observation_count']]
    weight_paths=[out.with_name(out.stem+f'_weight_{i}.png') for i in range(1,len(records)+1)]
    outputs={p.resolve() for p in [out,out.with_suffix('.json'),*auxiliary,*weight_paths]}
    if any(Path(r['image']).resolve() in outputs or Path(r['image']).with_suffix('.json').resolve() in outputs for r in records):
        raise ValueError('Blend output must not overwrite sources')
    grid=None; numerator=denominator=best=dominant=count=None; sources=[]
    weights=[]
    for index,record in enumerate(records,1):
        path=Path(record['image']);meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        stamp=utc_time(meta['observed_utc'])
        current=(meta['width'],meta['height'])
        if (meta.get('product')!='ir-gray' or meta.get('display_recipe')!=IR_GRAY_RECIPE
                or meta.get('display_mapping')!={'cold_white_c':-100,'warm_black_c':45}
                or meta.get('projection')!='EPSG:4326' or meta.get('extent_wsen')!=[-180,-90,180,90]
                or current[0]!=current[1]*2 or (grid is not None and grid!=current)):
            raise ValueError('Matching corrected observed grayscale global grids required')
        with Image.open(path) as im:
            if im.mode!='RGBA' or im.size!=current:raise ValueError('Source image differs from its grid')
            pixels=np.asarray(im)
        if not np.isin(pixels[...,3],[0,255]).all() or not (pixels[...,0]==pixels[...,1]).all() or not (pixels[...,1]==pixels[...,2]).all():
            raise ValueError('Binary observed coverage and grayscale RGB required')
        if grid is None:
            grid=current; shape=(grid[1],grid[0])
            numerator=np.zeros(shape,dtype=np.float32);denominator=np.zeros_like(numerator)
            best=np.zeros_like(numerator);dominant=np.zeros(shape,dtype=np.uint8);count=np.zeros_like(dominant)
        mask=pixels[...,3]==255
        weight=edge_weight(mask,feather)
        lon=-180+(np.arange(grid[0])+.5)*360/grid[0]
        for row in range(0,grid[1],128):
            sl=slice(row,min(row+128,grid[1]));lat=90-(np.arange(sl.start,sl.stop)+.5)*180/grid[1]
            weight[sl]*=view_weight(lon[None,:],lat[:,None],record['geometry'])
        weight[~mask]=0
        numerator+=pixels[...,0]*weight;denominator+=weight;count+=mask.astype(np.uint8)
        winner=weight>best;dominant[winner]=index;best[winner]=weight[winner]
        weights.append(weight)
        sources.append({'index':index,**record,'provenance':meta,
                        'offset_seconds':(stamp-reference_utc).total_seconds(),'observed_pixels':int(mask.sum())})
    coverage=count>0
    gray=np.rint(np.divide(numerator,denominator,out=np.zeros_like(numerator),where=denominator>0)).astype(np.uint8)
    rgba=np.dstack([gray,gray,gray,coverage.astype(np.uint8)*255])
    out.parent.mkdir(parents=True,exist_ok=True)
    Image.fromarray(rgba).save(out)
    Image.fromarray(dominant).save(auxiliary[0]);Image.fromarray(count).save(auxiliary[1])
    for weight,path in zip(weights,weight_paths):
        normalized=np.divide(weight,denominator,out=np.zeros_like(weight),where=coverage)
        Image.fromarray(np.rint(normalized*255).astype(np.uint8)).save(path)
    metadata={'product':'ir-gray-display-blend','display_recipe':'view-angle-edge-weighted-display-v1',
              'reference_utc':reference_utc.isoformat().replace('+00:00','Z'),
              'projection':'EPSG:4326','extent_wsen':[-180,-90,180,90],'width':grid[0],'height':grid[1],
              'sources':sources,'feather_grid_pixels':feather,
              'weight_formula':'(max(spherical_view_cosine,0)+0.001)^4 * min(distance_inside_observed_mask/feather,1)^2; normalized over valid sources only',
              'weight_maps':[p.name for p in weight_paths],'weight_map_quantization':'8-bit inspection only; exact weights reconstructed from formula',
              'dominant_source_map':auxiliary[0].name,'observation_count_map':auxiliary[1].name,
              'observed_pixels':int(coverage.sum()),'missing_pixels':int((~coverage).sum()),
              'is_single_sensor_observation':False,'is_radiometrically_calibrated_fusion':False,
              'is_interpolated_time':False,'is_gap_filled':False,
              'limitations':'Derived weighted display, not scientific single-sensor brightness temperatures. '
                            'No histogram matching, global brightness shifts or spatial image blur. '
                            'Nominal spherical viewing-angle approximation. Different scans, spectral responses, '
                            'parallax and limb artifacts remain; overlap mixing may soften moving cloud edges.'}
    out.with_suffix('.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    return out
