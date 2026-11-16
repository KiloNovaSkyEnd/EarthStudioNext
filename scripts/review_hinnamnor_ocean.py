"""Ocean ablations and fixed-camera observed twilight video; opt-in material only."""
import argparse
import json
from pathlib import Path
import time
import subprocess
import numpy as np
from PIL import Image,ImageDraw
import imageio_ffmpeg
from ges.storage import load_config
from ges.catalog import utc_time
from ges.solar import sun_direction,solar_weights
from ges.atmosphere_scattering import geographic
from ges.goni_film import NativeCloudRenderer
from ges.film_transition import load_reference
from scripts.audit_render_baseline import difference
from scripts.compare_hinnamnor_geocolor import sha

STAMPS=['0930','0940','0950','1000','1010','1020','1030']
SETTINGS=dict(volume=True,atmosphere=True,airglow=True,exposure=1.,city_lights=True,
              clouds=True,ocean_reflections=True,height_scale=.4,thickness=.8,volume_samples=96)


def resources(width,height):
    cfg=load_config()
    day,_=load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',4096,
                         'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night,_=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',4096,
                           'static reference night-lights composite, not contemporaneous with satellite clouds')
    water=np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    return NativeCloudRenderer(day,night,width,height,1,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)


def camera(wide=False):
    return {'position':geographic(109 if wide else 118,25 if wide else 23,10571 if wide else 9371),
            'target':geographic(128.2,25,6371),'up':np.array([0.,0.,1.]),'fov':38 if wide else 32}


def frame(stamp,diagnostic=False):
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_ocean_v1'
    if diagnostic:
        src=cfg.processed_dir/'hinnamnor_geocolor_v1'/stamp
        material=cfg.processed_dir/'hinnamnor_low_tint_v1'/stamp/'B_current_material_rgba.png'
    else:
        dest=root/stamp;src=Path(json.loads((dest/'source_location.json').read_text())['source_directory'])
        material=dest/'B_current_material_rgba.png'
    meta=json.loads((src/'official_metadata.json').read_text());projection=meta['projection'].copy()
    projection['b']=projection['a']*(1-1/projection['rf'])
    with np.load(src/'l2_observed_roi.npz') as f:
        h,err=f['CldTopHght'],f['ZcError'];good=np.isin(f['CloudMask'],[2,3])&(f['CloudMaskQualFlag']==0)&(f['CloudHgtQF']==0)
        good&=np.isfinite(h)&(h>0)&(h<=20000)&np.isfinite(err)&(err>=0)&(err<=3000)
        height=np.where(good,h/1000,np.nan).astype(np.float32)
    return np.asarray(Image.open(material).convert('RGBA')),height,{'projection':projection,'extent_m':meta['area_extent_m']},meta,src


def pair(path,left,right,title):
    out=Image.new('RGB',(left.shape[1]*2,left.shape[0]+32),'#0b1019')
    out.paste(Image.fromarray(left),(0,32));out.paste(Image.fromarray(right),(left.shape[1],32))
    ImageDraw.Draw(out).text((12,8),title,fill='white');out.save(path)


def diagnose():
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_ocean_v1';dst=root/'diagnostics';dst.mkdir(exist_ok=False)
    engine=resources(1280,720);cam=camera(True);records=[]
    cases={'legacy':{},'candidate':{'deep_ocean_material':True},
           'no_clouds':{'clouds':False},'no_atmosphere':{'atmosphere':False},
           'no_reflections':{'ocean_reflections':False},'no_airglow':{'airglow':False},
           'no_lights':{'city_lights':False},'exposure_075':{'exposure':.75},
           'clear_no_atmosphere':{'clouds':False,'atmosphere':False,'airglow':False},
           'clear_candidate_no_atmosphere':{'clouds':False,'atmosphere':False,'airglow':False,'deep_ocean_material':True}}
    try:
        for stamp in ['0830','1000','1130']:
            rgba,h,meta,obs,src=frame(stamp,True);engine.update(rgba,h,meta);sun=sun_direction(utc_time(obs['nominal_utc']));images={}
            for name,override in cases.items():
                pixels=engine.render(cam,sun,**{**SETTINGS,**override});images[name]=pixels
                Image.fromarray(pixels).save(dst/(stamp+'_'+name+'.png'))
            # Paired ablations are marginal effects, not additive causal decomposition.
            impacts={name:difference(images['legacy'],pixels) for name,pixels in images.items() if name!='legacy'}
            for name in ['candidate','no_clouds','no_atmosphere','no_reflections','no_airglow','no_lights']:
                pair(dst/(stamp+'_'+name+'_pair.png'),images['legacy'],images[name],stamp+' UTC | LEFT legacy / RIGHT '+name)
            records.append({'utc':obs['nominal_utc'],'marginal_image_differences':impacts})
            print('DIAGNOSTICS READY',stamp,flush=True)
        gpu=engine.device
    finally:engine.close()
    (dst/'verification.json').write_text(json.dumps({'samples':records,'gpu':gpu,'camera':{k:np.asarray(v).tolist() for k,v in cam.items()},
        'settings':SETTINGS,'limits':'Whole-frame differences, not ocean-only or independent additive contributions; cloud-off is a synthetic diagnostic, not a clear-sky observation.'},indent=2),encoding='utf-8')


def tagged(pixels,stamp,revision):
    im=Image.fromarray(pixels);d=ImageDraw.Draw(im);d.rectangle((0,0,im.width,60),fill='#0b1019')
    d.text((16,10),'HINNAMNOR | '+revision+' | 2022-08-31 '+stamp[:2]+':'+stamp[2:]+' UTC',fill='white')
    d.text((16,30),'7 real scans / 10-minute cadence | 24 held display frames per observation | no weather interpolation',fill='#c2cfde')
    return np.asarray(im).copy()


def writer(path,size):
    stream=imageio_ffmpeg.write_frames(str(path),size,fps=24,codec='libx264',pix_fmt_in='rgb24',pix_fmt_out='yuv420p',
        quality=8,macro_block_size=2,output_params=['-preset','fast','-movflags','+faststart','-threads','2',
            '-vf','scale=in_range=full:out_range=tv:out_color_matrix=bt709,setparams=range=limited:color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709',
            '-colorspace','bt709','-color_primaries','bt709','-color_trc','iec61966-2-1','-color_range','tv'])
    stream.send(None);return stream


def video():
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_ocean_v1';out=root/'video';out.mkdir(exist_ok=False)
    assert all((root/s/'material_metadata.json').exists() for s in STAMPS)
    engine=resources(3840,2160);cam=camera();started=time.monotonic();records=[];previous=None;temporal=[];inputs={}
    writers={name:writer(out/(name+'.mp4'),size) for name,size in
             [('legacy_4k',(3840,2160)),('candidate_4k',(3840,2160)),('AB_1080p',(3840,1080))]}
    try:
        for index,stamp in enumerate(STAMPS):
            rgba,h,meta,obs,src=frame(stamp);engine.update(rgba,h,meta);utc=utc_time(obs['nominal_utc']);sun=sun_direction(utc);images={}
            for name,enabled in [('legacy',False),('candidate',True)]:
                pixels=engine.render(cam,sun,**SETTINGS,deep_ocean_material=enabled)
                images[name]=pixels;Image.fromarray(pixels).save(out/(stamp+'_'+name+'_4k.png'))
                labelled=tagged(pixels,stamp,name)
                for _ in range(24):writers[name+'_4k'].send(labelled)
            pair_frame=np.concatenate([np.asarray(Image.fromarray(tagged(images[n],stamp,n)).resize((1920,1080),Image.Resampling.LANCZOS)) for n in ['legacy','candidate']],axis=1)
            for _ in range(24):writers['AB_1080p'].send(pair_frame)
            Image.fromarray(pair_frame).save(out/(stamp+'_pair_1080p.png'))
            with np.load(root/stamp/'material_layers.npz') as f:
                alpha=f['alpha'];low=f['low_confidence']
                if previous is not None:
                    da=np.abs(alpha-previous[0]);temporal.append({'from':STAMPS[index-1],'to':stamp,
                        'material_alpha_mean_abs_change':float(da.mean()),'material_alpha_p99_abs_change':float(np.quantile(da,.99)),
                        'nonzero_support_lost_pixels':int(((previous[0]>0)&(alpha==0)).sum()),
                        'nonzero_support_gained_pixels':int(((previous[0]==0)&(alpha>0)).sum()),
                        'low_support_changed_native_pixels':int(((low>0)!=(previous[1]>0)).sum())})
                previous=(alpha,low)
            metadata=json.loads((root/stamp/'material_metadata.json').read_text())
            records.append({'nominal_utc':obs['nominal_utc'],'encoded_frames':[index*24,index*24+23],
                            'sun_elevation_at_fixed_target_deg':float(solar_weights(utc,128.2,25).elevation_deg),
                            'bands':obs['bands'],'material':metadata,'legacy_candidate_render_difference':difference(images['legacy'],images['candidate'])})
            for file in [src/'observed_inputs.npz',src/'l2_observed_roi.npz',root/stamp/'B_current_material_rgba.png']:
                inputs[str(file.resolve())]=sha(file)
            print('4K SCAN READY',stamp,'elapsed',round(time.monotonic()-started,1),flush=True)
        gpu=engine.device
    finally:
        engine.close()
        for stream in writers.values():stream.close()
    decoded={}
    for path in out.glob('*.mp4'):
        reader=imageio_ffmpeg.read_frames(str(path));info=next(reader);count=0;roundtrip=[]
        for pixels in reader:
            if count in [0,72,144]:
                stamp=STAMPS[count//24]
                if path.stem=='AB_1080p':expected=np.asarray(Image.open(out/(stamp+'_pair_1080p.png')))
                else:
                    revision=path.stem.split('_')[0]
                    expected=tagged(np.asarray(Image.open(out/(stamp+'_'+revision+'_4k.png'))),stamp,revision)
                decoded_pixels=np.frombuffer(pixels,np.uint8).reshape(expected.shape)
                d=difference(decoded_pixels,expected);assert d['mean_dn']<3,(path,count,d)
                roundtrip.append({'frame':count,**d})
            count+=1
        assert count==168 and info['fps']==24,(path,count,info)
        probe=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-i',str(path),'-frames:v','1','-f','null','-'],capture_output=True,text=True,check=True)
        video_info=[s.strip() for s in probe.stderr.splitlines() if 'Video:' in s]
        assert any('bt709/bt709/iec61966-2-1' in s for s in video_info),(path,video_info)
        decoded[path.name]={'frames':count,'size':info['size'],'fps':info['fps'],'bytes':path.stat().st_size,'sha256':sha(path),
                            'png_to_video_roundtrip_samples':roundtrip,'color_tag_probe':video_info}
    result={'samples':records,'temporal_changes':temporal,'encoded_videos':decoded,'gpu':gpu,
            'camera':{k:np.asarray(v).tolist() for k,v in cam.items()},'settings':SETTINGS,'input_sha256':inputs,
            'real_acquisitions':7,'observation_cadence_seconds':600,'display_hold_frames_per_acquisition':24,
            'weather_interpolation':False,'elapsed_seconds':time.monotonic()-started,
            'limits':'Only short pilot; no automatic full-window expansion. Source cloud support changes can include retrieval quality and solar transfer, not only weather. Model ocean reflectance is not observed sea state. Existing seams/stripes are not fixed.'}
    (out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('VIDEO DECODE PASS',json.dumps(decoded),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--diagnose',action='store_true');p.add_argument('--video',action='store_true');a=p.parse_args()
    if a.diagnose:diagnose()
    elif a.video:video()
    else:p.error('Choose --diagnose or --video')
