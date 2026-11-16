"""Actual fixed-source camera/solar test films; never weather time-series claims."""
from pathlib import Path
from datetime import timedelta
import json,hashlib,argparse,time
import numpy as np
from PIL import Image,ImageDraw
import imageio_ffmpeg
from ges.catalog import utc_time
from ges.solar import sun_direction
from ges.atmosphere_scattering import ScatteringRenderer,geographic,orbit_camera
from ges.film_transition import load_reference,daylight_display
from ges.blend_night import linear_rgb,encode_rgb

ROOT=Path(__file__).resolve().parents[1]


def load_images(folder,width=8192):
    source=ROOT/'data/processed/day_night_v9/earth_day_night.png';meta=json.loads(source.with_suffix('.json').read_text())
    def image(path,mode='RGB'):
        return np.asarray(Image.open(path).convert(mode).resize((width,width//2),Image.Resampling.LANCZOS)).copy()
    current=image(source);base=Path(meta['baseline_image']);irpath=Path(meta['night_image']);nm=meta['night_source']
    ir=image(irpath,'RGBA');ca=ir[...,3:4].astype(np.float32)/255
    ng,_=load_reference(ROOT/'data/raw/reference/BlackMarble_2016_3km.jpg',width,'static reference night-lights composite, not contemporaneous with satellite clouds')
    ng=np.maximum(ng,(4,5,12)).astype(np.uint8);night=np.rint(ir[...,:3]*ca+ng*(1-ca)).astype(np.uint8)
    dg,_=load_reference(ROOT/'data/raw/reference/BlueMarble_200410_topography_8km.jpg',width,'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    a=image(base.with_name(base.stem+'_observed_vis_alpha.png'),'L').astype(np.float32)/255
    # Resize masks only with nearest; missing VIS never becomes observed VIS.
    cov=np.asarray(Image.open(base.with_name(base.stem+'_observed_vis_coverage.png')).resize((width,width//2),Image.Resampling.NEAREST))>0
    a=np.where(cov,a,ca[...,0]);a,dl=daylight_display(a,dg,'sunlit-v1')
    day=np.rint(255*a[...,None]+encode_rgb(dl)*(1-a[...,None])).astype(np.uint8)
    rgb=image(source.with_name(source.stem+'_observed_rgb.png'))
    support=image(source.with_name(source.stem+'_observed_rgb_support.png'),'L').astype(np.float32)/255
    day=encode_rgb(linear_rgb(rgb)*support[...,None]+linear_rgb(day)*(1-support[...,None]))
    # These are display fixtures from frozen actual fields, NOT new observed UTC.
    Image.fromarray(day).save(folder/'frozen_day_fixture.png');Image.fromarray(night).save(folder/'frozen_night_fixture.png')
    return [current,day,night],meta,source


def label(pixels,title,detail):
    im=Image.fromarray(pixels);draw=ImageDraw.Draw(im)
    draw.rectangle((0,0,im.width,50),fill=(8,12,18));draw.text((12,8),title,fill='white');draw.text((12,28),detail,fill=(200,210,225))
    return np.asarray(im).copy()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--frames',type=int,default=720);parser.add_argument('--width',type=int,default=1280);parser.add_argument('--stills-only',action='store_true')
    parser.add_argument('--out',default='data/processed/atmosphere_scattering_v3');args=parser.parse_args()
    folder=ROOT/args.out;folder.mkdir(parents=True,exist_ok=True)
    images,meta,source=load_images(folder);stamp=utc_time(meta['reference_utc']);sun=sun_direction(stamp)
    renderer=ScatteringRenderer(images,args.width,args.width*9//16,supersample=1.5);print('GPU',renderer.device,flush=True)
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest();comparisons=[]
    # User-facing scope is orbital distance, not the former40km stress fixture.
    for name,lon,alt in [('orbital_day',-75,1200),('closer_orbit_day',-75,600),('twilight_side',-5,1500),('night_side',135,1500)]:
        camera=orbit_camera(lon,15,alt,fov=45,heading=1)
        for state,on,glow in [('off',False,False),('on',True,True)]:
            pixels=renderer.render(camera,sun,enabled=on,airglow=glow,steps=96,sun_steps=20)
            Image.fromarray(pixels).save(folder/(name+'_'+state+'.png'))
        comparisons.append(name);print('STILL',name,flush=True)
    # Integration convergence assessed on a real grazing daylight camera.
    camera=orbit_camera(-75,15,1200,fov=45)
    low=renderer.render(camera,sun,steps=48,sun_steps=12,float_output=True)
    high=renderer.render(camera,sun,steps=96,sun_steps=24,float_output=True)
    diff=abs(low[...,:3]-high[...,:3])*255
    convergence={'low_samples':[48,12],'high_samples':[96,24],
        'mean_display_dn':float(diff.mean()),'p99_display_dn':float(np.quantile(diff,.99)),'max_display_dn':float(diff.max())}
    # Exactly same solar/camera inputs reproduce identical output.
    again=renderer.render(camera,sun,steps=48,sun_steps=12,float_output=True)
    np.testing.assert_array_equal(low,again)
    # Cross the 100km top boundary in 20m; no branch-induced strip discontinuity.
    near=[]
    for alt in [99.99,100.,100.01]:
        near.append(renderer.render(orbit_camera(-75,15,alt),sun,steps=96,sun_steps=24,float_output=True))
    boundary=[float(abs(near[i+1][...,:3]-near[i][...,:3]).mean()*255) for i in range(2)]
    assert max(boundary)<1.,('Atmosphere entry jump',boundary)
    films=[]
    if not args.stills_only:
        for kind in ['fixed_camera_day_to_night','grazing_terminator_flyby']:
            writer=imageio_ffmpeg.write_frames(str(folder/(kind+'.mp4')),(renderer.width,renderer.height),fps=24,
                codec='libx264',pix_fmt_in='rgb24',pix_fmt_out='yuv420p',quality=8,macro_block_size=2,output_params=['-movflags','+faststart'])
            writer.send(None);frames=[];prior=None;step_stats=[];started=time.monotonic()
            try:
                for frame in range(args.frames):
                    u=frame/max(1,args.frames-1)
                    eased=u**3*(u*(6*u-15)+10)
                    if kind=='fixed_camera_day_to_night':
                        when=stamp+timedelta(hours=-2+6*u);direction=sun_direction(when)
                        camera={'position':geographic(-5,15,22000),'target':np.zeros(3),'up':np.array([0,0,1.]),'fov':40}
                        pixels=renderer.render(camera,direction,airglow=True,dynamic=True,steps=64,sun_steps=16)
                        detail=when.strftime('SUN ONLY %H:%M UTC')+' | clouds fixed 2020-10-29 16:40 UTC; NOT weather time series'
                    else:
                        altitude=600+2400*np.sin(np.pi*eased)**2
                        camera=orbit_camera(-105-70*eased,15,altitude,fov=45,heading=-1)
                        pixels=renderer.render(camera,sun,airglow=True,steps=64,sun_steps=16)
                        detail=f'UTC fixed 2020-10-29 16:40 | altitude {altitude:.1f} km | camera motion only'
                    if prior is not None:
                        delta=abs(pixels.astype(np.int16)-prior.astype(np.int16))
                        step_stats.append({'mean_dn':float(delta.mean()),'p99_dn':float(np.quantile(delta,.99))})
                    prior=pixels
                    title='SINGLE SCATTERING - '+kind.replace('_',' ').upper()
                    labelled=label(pixels,title,detail);writer.send(labelled)
                    if frame in {0,args.frames//4,args.frames//2,3*args.frames//4,args.frames-1}:
                        Image.fromarray(labelled).save(folder/(kind+f'_{frame:04d}.png'));frames.append(frame)
                    if frame%30==0:print('FILM',kind,frame,'/',args.frames,'seconds',round(time.monotonic()-started,1),flush=True)
            finally:writer.close()
            films.append({'file':kind+'.mp4','frames':args.frames,'fps':24,'keyframes':frames,
                'max_mean_dn_per_frame':max(x['mean_dn'] for x in step_stats),'max_p99_dn_per_frame':max(x['p99_dn'] for x in step_stats),
                'motion_differences_are_not_automatically_flicker':True})
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
    report={'passed':True,'source_utc':meta['reference_utc'],'source_sha256_unchanged':source_hash,
        'model':'numerical single Rayleigh/Mie scattering, approximate ozone, volume-integrated optional airglow',
        'length_unit':'km','rayleigh_scale_height_km':8,'mie_scale_height_km':1.2,'mie_g':.8,
        'gpu':renderer.device,'output_dimensions':[renderer.width,renderer.height],'source_image_dimensions':list(images[0].shape[:2][::-1]),
        'spatial_supersampling':1.5,'anisotropic_filtering':16,'no_temporal_random_jitter':True,
        'main_camera_altitude_km':[600,3000],'camera_path_easing':'C2 zero velocity/acceleration at endpoints',
        'convergence':convergence,'camera_top_boundary_20m_mean_dn_steps':boundary,'deterministic_repeat_exact':True,
        'films':films,'still_comparisons':comparisons,'is_satellite_atmosphere_retrieval':False,
        'not_complete_multiple_scattering':True,'polar_data_added':False,
        'limitations':'Standard atmosphere, not measured aerosol/airglow; single scattering only. Surface is existing RGB/IR display, not calibrated albedo, no true cloud height. Solar sweep freezes cloud fields and uses explicitly constructed display fixtures, NOT a weather time series or new VIS observations. No guarantee for all future arbitrary camera paths.'}
    (folder/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');renderer.close()
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
