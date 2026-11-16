"""Ocean-source forensics only: original references and aligned actual AHI evidence."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import map_coordinates

from ges.catalog import utc_time
from ges.solar import solar_weights, sun_direction

ROOT=Path(__file__).resolve().parents[1]
IDS=['000061','000064','000031','000067','000019']


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')


def sample_geo(a,lon,lat):
    h,w=a.shape[:2];xy=[(90-lat)*h/180-.5,(lon+180)*w/360-.5]
    if a.ndim==2:return map_coordinates(a,xy,order=1,mode='nearest')
    return np.stack([map_coordinates(a[:,:,c],xy,order=1,mode='nearest') for c in range(a.shape[2])],axis=-1)


def save_rgb(p,a,mask=None):
    rgb=np.rint(np.clip(np.nan_to_num(a),0,1)*255).astype(np.uint8)
    if mask is not None:rgb=np.dstack([rgb,np.where(mask,255,0).astype(np.uint8)])
    Image.fromarray(rgb).save(p)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--references',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--resume',action='store_true',help='Explicitly regenerate this research output, never raw inputs')
    args=ap.parse_args();args.out.mkdir(exist_ok=True);(args.out/'references').mkdir(exist_ok=args.resume)
    manifest=[];board=Image.new('RGB',(1800,760),'#101722');draw=ImageDraw.Draw(board)
    for k,ident in enumerate(IDS):
        p=args.references/f'10月19日_{ident}.png'
        with Image.open(p) as im:
            im.load();rec=dict(file=str(p.resolve()),sha256=sha(p),size=im.size,mode=im.mode,bytes=p.stat().st_size,observation_utc=None)
            thumb=im.copy();thumb.thumbnail((600,338),Image.Resampling.LANCZOS)
            x=(k%3)*600;y=(k//3)*380;board.paste(thumb,(x,y+36));draw.text((x+8,y+8),'SDK '+ident+' | UTC / camera unknown',fill='white')
            # Native crop selected for visible water / thin cloud relationships;
            # not an independently confirmed clear-water mask.
            box=(round(im.width*.67),round(im.height*.45),round(im.width*.94),round(im.height*.76))
            im.crop(box).save(args.out/'references'/f'{ident}_water_cloud_native.png');rec['native_crop_box']=box
            manifest.append(rec)
    board.save(args.out/'reference_contact.jpg');dump(args.out/'reference_manifest.json',manifest)
    base=ROOT/'data/processed/hinnamnor_geocolor_v1/0830'
    with np.load(base/'observed_inputs.npz') as z:
        lon=z['longitude_2km'];lat=z['latitude_2km'];b03=z['B03_fraction_1km'].reshape(lon.shape[0],2,lon.shape[1],2).mean(axis=(1,3))
    with np.load(base/'l2_observed_roi.npz') as z:l2={k:z[k] for k in z.files}
    with np.load(base/'official_layers.npz') as z:
        raw_day=z['official_day_rgb']
        negative=(raw_day<0).any(-1).reshape(lon.shape[0],2,lon.shape[1],2).any(axis=(1,3))
        # Match official display export order: clip each enhanced 1km sample,
        # then area-average to the common native 2km diagnostic grid.
        day=np.clip(raw_day,0,1).reshape(lon.shape[0],2,lon.shape[1],2,3).mean(axis=(1,3))
    water=np.asarray(Image.open(ROOT/'data/processed/cloud_relief_v4/static_ocean_mask.png').convert('L'),np.float32)/255
    sea=sample_geo(water,lon,lat)>.999
    stamp=utc_time('2022-08-31T08:30:00Z');e=solar_weights(stamp,lon,lat).elevation_deg
    n=np.stack([np.cos(np.deg2rad(lat))*np.cos(np.deg2rad(lon)),np.cos(np.deg2rad(lat))*np.sin(np.deg2rad(lon)),np.sin(np.deg2rad(lat))],-1)
    satellite=np.array([np.cos(np.deg2rad(140.7)),np.sin(np.deg2rad(140.7)),0])*42164
    v=satellite-n*6371;v/=np.linalg.norm(v,axis=-1,keepdims=True)
    nv=(n*v).sum(-1);sun=sun_direction(stamp)
    glint=np.rad2deg(np.arccos(np.clip(2*nv*(n*sun).sum(-1)-(v*sun).sum(-1),-1,1)))
    clear=sea&(l2['CloudMask']==0)&(l2['CloudMaskQualFlag']==0)&np.isfinite(l2['CloudProbability'])&(l2['CloudProbability']<=.05)&(e>=10)&(nv>=.5)&(glint>=30)&np.isfinite(day).all(-1)
    assert clear.any(),'No valid actual clear-water evidence in selected geometry'
    stats={};samples={}
    for label,name in [('current_topography','BlueMarble_200410_topography_8km.jpg'),('bathymetry_not_water_colour','BlueMarble_200410_8km.jpg')]:
        p=ROOT/'data/raw/reference'/name
        with Image.open(p) as im:a=np.asarray(im.convert('RGB'),np.float32)/255
        sampled=sample_geo(a,lon,lat);samples[label]=sampled
        pix=np.rint(sampled[clear]*255).astype(np.uint8);colors,counts=np.unique(pix,axis=0,return_counts=True);i=counts.argmax()
        stats[label]=dict(sha256=sha(p),clear_proxy_pixels=int(clear.sum()),mode_rgb=colors[i].tolist(),mode_fraction=float(counts[i]/counts.sum()),rgb_p01_p50_p99=np.percentile(pix,[1,50,99],axis=0).tolist(),unique_rgb=int(len(colors)))
        save_rgb(args.out/(label+'_same_grid.png'),sampled)
        save_rgb(args.out/(label+'_clear_only.png'),sampled,clear)
    save_rgb(args.out/'AHI_official_day_rgb_same_grid.png',day)
    save_rgb(args.out/'AHI_official_day_clear_only.png',day,clear)
    Image.fromarray((clear*255).astype(np.uint8)).save(args.out/'clear_water_proxy.png')
    Image.fromarray(np.rint(np.clip(b03,0,1)*255).astype(np.uint8)).save(args.out/'observed_B03_2km.png')
    stats['observed_AHI']=dict(nominal_utc=stamp.isoformat(),shape=list(lon.shape),clear_proxy_pixels=int(clear.sum()),
        display_rgb_p01_p50_p99=np.percentile(day[clear]*255,[1,50,99],axis=0).tolist(),
        observed_B03_fraction_p01_p50_p99=np.percentile(b03[clear],[1,50,99]).tolist(),
        solar_elevation_p01_p50_p99=np.percentile(e[clear],[1,50,99]).tolist(),
        clear_proxy_blocks_with_preexport_negative_RGB_fraction=float(negative[clear].mean()),
        display_export='Clip enhanced samples to0..1 before 2x2 area mean, consistent with official PNG limits. Preexport negative values are not negative ocean radiance.',
        geometry='spherical diagnostic view/glint only, not an ocean atmospheric correction',
        warning='Official enhanced Rayleigh-corrected RGB is apparent/display colour, not retrieved Rrs, albedo, cloud-free truth or a replacement 3D texture')
    stats['clear_definition']='CMSK clear0/QF0, probability<=0.05, conservative static water>.999, sun>=10deg, view cosine>=0.5, glint angle>=30deg, finite RGB. Remaining aerosol/thin cloud and L2 errors possible.'
    dump(args.out/'source_forensics.json',stats)
    np.savez_compressed(args.out/'aligned_water_evidence.npz',longitude=lon,latitude=lat,clear_proxy=clear,observed_day_rgb=day,static_ground_rgb=samples['current_topography'],solar_elevation=e,glint_angle=glint)
    panel=Image.new('RGB',(2400,650),'#101722');dr=ImageDraw.Draw(panel)
    paths=[args.out/'current_topography_clear_only.png',args.out/'AHI_official_day_clear_only.png',args.out/'bathymetry_not_water_colour_clear_only.png']
    for i,(p,title) in enumerate(zip(paths,['Current ground | same clear proxy','Real AHI display RGB | NOT Rrs/albedo','Bathymetry | NOT a true-colour fix'])):
        with Image.open(p) as im:
            canvas=Image.new('RGB',im.size,'#151c27');canvas.paste(im,mask=im.getchannel('A'));canvas.thumbnail((800,614),Image.Resampling.LANCZOS)
            panel.paste(canvas,(i*800,36))
        dr.text((i*800+8,10),title,fill='white')
    panel.save(args.out/'same_grid_clear_water_comparison.jpg')
    print(json.dumps(stats,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
