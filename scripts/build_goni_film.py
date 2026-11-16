"""Actual Goni timelapse review: fixed nadir/oblique/detail, no invented frames."""
from pathlib import Path
import argparse
import hashlib
import json
import time
import numpy as np
from PIL import Image,ImageDraw
import imageio_ffmpeg
from ges.storage import load_config
from ges.film_transition import load_reference
from ges.solar import sun_direction,solar_weights
from ges.catalog import utc_time
from ges.goni_film import NativeCloudRenderer
from ges.atmosphere_scattering import geographic
from scripts.review_cloud_relief import angles
from scripts.prepare_ocean_reference import fetch_land,ocean_mask


def cameras():
    return {
        'nadir':{'position':geographic(132,16.4,9371),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':38},
        'oblique':{'position':geographic(113,16.4,10571),'target':geographic(132,16.4,6371),'up':np.array([0.,0.,1.]),'fov':38},
        'detail':{'position':geographic(132,16.4,7971),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':32}}


def label(pixels,title,stamp):
    image=Image.fromarray(pixels);draw=ImageDraw.Draw(image)
    draw.rectangle((0,0,image.width,38),fill=(8,12,18))
    draw.text((12,7),title+' | Himawari-8 | '+stamp.strftime('%Y-%m-%d %H:%M UTC scene'),fill='white')
    draw.text((12,23),'Observed20min cadence; repeated display frames | retrieved tops + model thickness',fill=(175,190,210))
    return np.asarray(image).copy()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stills-only',action='store_true');parser.add_argument('--width',type=int,default=1280)
    parser.add_argument('--wait',action='store_true',help='Wait for all actual processed frames before final encoding')
    args=parser.parse_args();cfg=load_config();folder=cfg.processed_dir/'goni_film_v1'
    rendered=folder/('diagnostics_v2' if args.stills_only else 'rendered_v2');rendered.mkdir(exist_ok=True)
    if args.wait:
        began=time.monotonic();seen=-1
        while True:
            paths=list((folder/'frames').glob('*/frame.json'))
            try:ready=sum(json.loads(p.read_text()).get('material_revision')==6 for p in paths)
            except json.JSONDecodeError:ready=0
            if ready!=seen:print('WAIT refined actual acquisitions',ready,'/31',flush=True);seen=ready
            if len(paths)==31 and ready==31:break
            if time.monotonic()-began>7200:raise TimeoutError('Actual observations not ready within bounded wait')
            time.sleep(5)
    frames=[json.loads(p.read_text()) for p in sorted((folder/'frames').glob('*/frame.json'))]
    if not frames:raise ValueError('No actual processed acquisition available')
    if not args.stills_only and (len(frames)!=31 or any(m.get('material_revision')!=6 for m in frames)):
        raise ValueError('31 actual IR-refined acquisitions required before weather movies')
    day,dm=load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',5400,
                          'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night,nm=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',13500,
                           'static reference night-lights composite, not contemporaneous with satellite clouds')
    land,land_meta=fetch_land();water=ocean_mask(land,4096)
    renderer=NativeCloudRenderer(day,night,args.width,args.width*9//16,supersample=1.25,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
    gpu=renderer.device;camera_set=cameras()
    def angle_report(camera):
        target=camera['target']
        if np.linalg.norm(target)<1:target=np.asarray(camera['position'])/np.linalg.norm(camera['position'])*6371
        return angles({**camera,'target':target})
    print('GPU',gpu,'VIEWS',[(k,angle_report(v)) for k,v in camera_set.items()],flush=True)
    elevations=[float(solar_weights(utc_time(m['nominal_utc']),132,16.4).elevation_deg) for m in frames]
    key_indices={0,min(range(len(frames)),key=lambda i:abs(elevations[i])),len(frames)-1}
    if args.stills_only:key_indices={0,len(frames)-1}
    writers={};encoded_indices=np.floor(np.arange(192)*len(frames)/192).astype(int);records=[];keyframes=[]
    if not args.stills_only:
        for view in camera_set:
            path=rendered/('goni_'+view+'_8s.mp4')
            writer=imageio_ffmpeg.write_frames(str(path),(renderer.width,renderer.height),fps=24,codec='libx264',
                pix_fmt_in='rgb24',pix_fmt_out='yuv420p',quality=8,macro_block_size=2,output_params=['-movflags','+faststart','-threads','2'])
            writer.send(None);writers[view]=writer
    started=time.monotonic()
    try:
        for i,m in enumerate(frames):
            if args.stills_only and i not in key_indices:continue
            root=Path(m['frame_directory']);material=root/m.get('render_material_file','cloud.png')
            rgba=np.asarray(Image.open(material).convert('RGBA'))
            with np.load(root/'height.npz') as f:height=f['height_km'].copy()
            cloud_hash=hashlib.sha256(material.read_bytes()).hexdigest()
            renderer.update(rgba,height,m);stamp=utc_time(m['nominal_utc']);sun=sun_direction(stamp);views={}
            for view,camera in camera_set.items():
                pixels=renderer.render(camera,sun,volume=True,atmosphere=True,airglow=True)
                tagged=label(pixels,'GONI | '+view,stamp)
                if i in key_indices:
                    name=f'{view}_{stamp:%H%M}.png';Image.fromarray(tagged).save(rendered/name);keyframes.append({'view':view,'source_index':i,'file':name})
                if not args.stills_only:
                    for _ in range(int(np.count_nonzero(encoded_indices==i))):writers[view].send(tagged)
                views[view]={'mean_dn':float(pixels.mean()),'max_dn':int(pixels.max())}
            if i in key_indices:
                baseline=renderer.render(camera_set['oblique'],sun,volume=False,atmosphere=True,airglow=True)
                volume=renderer.render(camera_set['oblique'],sun,volume=True,atmosphere=True,airglow=True)
                no_atmo=renderer.render(camera_set['oblique'],sun,volume=True,atmosphere=False,airglow=False)
                no_glow=renderer.render(camera_set['oblique'],sun,volume=True,atmosphere=True,airglow=False)
                for name,a,b in [('volume',baseline,volume),('atmosphere',no_atmo,volume),('airglow',no_glow,volume)]:
                    pair=Image.new('RGB',(renderer.width*2,renderer.height+30),(8,12,18));pair.paste(Image.fromarray(a),(0,30));pair.paste(Image.fromarray(b),(renderer.width,30))
                    ImageDraw.Draw(pair).text((12,9),f'{stamp:%Y-%m-%d %H:%M UTC} | {name} | LEFT control / RIGHT enabled',fill='white')
                    pair.save(rendered/(f'{name}_{stamp:%H%M}.png'))
                if 'render_material_file' in m:
                    previous=root/'cloud_revision2.png'
                    if not previous.exists():previous=root/'cloud.png'
                    renderer.update(np.asarray(Image.open(previous).convert('RGBA')),height,m)
                    old_material=renderer.render(camera_set['oblique'],sun,volume=True,atmosphere=True,airglow=True)
                    renderer.update(rgba,height,m)
                    pair=Image.new('RGB',(renderer.width*2,renderer.height+30),(8,12,18))
                    pair.paste(Image.fromarray(old_material),(0,30));pair.paste(Image.fromarray(volume),(renderer.width,30))
                    ImageDraw.Draw(pair).text((12,9),f'{stamp:%Y-%m-%d %H:%M UTC} | same lighting: LEFT binary mask / grey IR; RIGHT probability + restored low cloud',fill='white')
                    pair.save(rendered/(f'material_{stamp:%H%M}.png'))
            assert hashlib.sha256(material.read_bytes()).hexdigest()==cloud_hash
            records.append({'source_index':i,'utc':m['nominal_utc'],'actual_scan_interval':[m['scan_start_utc'],m['scan_end_utc']],
                            'cloud_sha256_unchanged':cloud_hash,'display_repeats':int(np.count_nonzero(encoded_indices==i)),
                            'display_interpolated_height_cells_not_observed':renderer.geometry_interpolated_cells,
                            'material_revision':m.get('material_revision'),'material_file':material.name,
                            'lowcloud_evidence':m.get('lowcloud_restoration'),'spectral_evidence':m.get('spectral_restoration'),
                            'daylight_evidence':m.get('daylight_restoration'),
                            'target_solar_elevation_deg':elevations[i],'views':views})
            print('RENDER',i+1,'/',len(frames),m['nominal_utc'],'seconds',round(time.monotonic()-started,1),flush=True)
    finally:
        for writer in writers.values():writer.close()
        renderer.close()
    films=[]
    if not args.stills_only:
        for view in camera_set:
            path=rendered/('goni_'+view+'_8s.mp4');reader=imageio_ffmpeg.read_frames(str(path));video_meta=next(reader);count=0
            for data in reader:count+=1
            if count!=192 or video_meta['size']!=(args.width,args.width*9//16) or abs(video_meta['fps']-24)>.01:
                raise ValueError('Encoded movie failed full decode verification')
            films.append({'file':path.name,'decoded_frames':count,'fps':video_meta['fps'],'duration_seconds':8,
                          'dimensions':video_meta['size'],'bytes':path.stat().st_size})
    raw_l2=sum(p.stat().st_size for p in (cfg.raw_dir/'goni_l2_ranges').rglob('*.bin'))
    inventory=json.loads((folder/'inventory.json').read_text());supplement=json.loads((folder/'shortwave_inventory.json').read_text())
    report={'recipe':'native-AHI-observed-Goni-cloud-column-volume-restored-spectral-v3','actual_acquisitions':len(frames),'stills_only':args.stills_only,
            'raw_budget':{'original_hsd_and_all_l2_including_retained_pilots_bytes':inventory['hsd_total_bytes']+raw_l2,
                          'original_batch_limit_bytes':int(cfg.max_single_scene_gb*1e9),'required_shortwave_supplement':supplement,
                          'combined_new_event_raw_bytes':inventory['hsd_total_bytes']+raw_l2+supplement['total_bytes']},
            'cadence_minutes':20,'is_weather_time_sequence':True,'generated_weather_frames':False,
            'display_timing':f'{len(frames)} actual acquisitions; final film repeats them across192 display frames at24fps; no crossfade, optical flow or synthesized weather',
            'geometry':'0.3+0.4*quality-screened retrieved cloud top km; unsupported cloud top0.9km is a labelled display assumption',
            'volume':'Radial column density6u(1-u), nominal max0.8km display thickness; base/extinction are approximations, NOT retrieved optical thickness or tomography',
            'day':'Measured B03 daytime VIS, original500m averaged to1km conservatively; measured tone separated from approximate opacity, smooth bright-cloud compression; no nighttime visible synthesis',
            'night':'Measured B13/B07 thermal IR display at native2km plus restored liquid/supercooled low-cloud tint constrained by phase/height/error/QF; LW-SW texture uses both actual-scan endpoint solar elevations<=-6deg; not true-visible night imagery',
            'cloud_edges':'Delivered CloudProbability replaces categorical gating inside documented ROI; mask retained outside. No generated radiance or RGB spatial blur. Probably-clear displayed weakly as uncertain probability, not relabelled confident cloud.',
            'lowcloud_evidence_roi_yx':[1200,2600,1600,3400],
            'cloud_lighting':'Measured VIS relit by UTC direct light, displayed column self-shadow and approximate solar cloud shadow on water. Night normal contrast uses fixed display direction, not retrieved moonlight. Cloud thickness/extinction are model assumptions',
            'source_projection':'Actual native AHI sweep-y grid retained; no intermediate8192 global map',
            'giant_sun_glint':False,'random_cloud_noise':False,'camera':{k:{a:np.asarray(b).tolist() for a,b in v.items()} for k,v in camera_set.items()},
            'display_opacity_gamma':1.25,'display_geometry':'sigma2 normalized display height; continuous confidence blend to fallback, no support threshold; measured support kept separately and raw NaNs unchanged',
            'integration':'Analytic6u(1-u) per radial segment; avoids missing thin slabs between midpoint samples',
            'water_model':{'static_mask':land_meta,'roughness':.55,'fresnel_f0':.0204,'specular_soft_limit_linear':.012,'sky':'approximate diffuse hemisphere','shadows':'approximate cloud display-alpha solar attenuation','observed_sea_state':False},
            'source_day_reference':dm,'source_night_reference':nm,'gpu':gpu,
            'keyframes':keyframes,'films':films,'records':records,
            'limits':'Not near100% reference-match acceptance. Low-phase/continuous-probability improvement restricted to documented native ROI; outside retains earlier observed VIS/IR with binary classification. Source IR2km limits small details; no retrieved cloud base or inside cloud structure. Static2004 ground/2016 lights. Standard approximate atmosphere/airglow; no measured sea state. Missing outside regional observation remains missing. Repeated source frames may visibly step; no weather interpolation claimed.'}
    (rendered/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not args.stills_only:
        cards=''.join(f'<h2>{view}</h2><video controls loop preload="metadata" src="goni_{view}_8s.mp4"></video>' for view in camera_set)
        reference_cards=''.join(f'<h3>{title}</h3><img src="../references/{name}.png">' for title,name in [('参考夜间','reference_night'),('参考过渡','reference_transition'),('参考白天','reference_day')])
        (rendered/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>天鹅：真实云图与体积近似</title>
<style>body{background:#0a1019;color:#dce8f6;font:16px system-ui;margin:24px}video,img{width:100%;max-width:1280px}a{color:#9cdbff}</style>
<h1>天鹅真实时序：俯视、斜视、近景细节</h1><p>2020-10-30 04:00–14:00 UTC，31个实际观测，20分钟间隔；每段8秒。屏幕重复帧不等于新增观测，没有插帧天气。白天实测可见光、夜间实测红外，静态地表/夜光参考。</p>
<p>实测云顶约束的体积显示近似；厚度、云底和密度不是实测反演。已取消太阳亮斑。未宣称接近100%复现参考作者效果。</p>'''+cards+'''
<h2>用户提供的视觉参考（其他台风事件）</h2>'''+reference_cards+'''
<p><a href="verification.json">完整来源、UTC、近似条件与解码验证</a></p>''',encoding='utf-8')
    print('REPORT',rendered/'verification.json',flush=True)


if __name__=='__main__':main()
