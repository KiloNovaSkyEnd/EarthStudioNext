"""Real-UTC terminator views and optional night-only display depth comparisons."""
import hashlib
import json
import numpy as np
from PIL import Image, ImageDraw
from ges.storage import load_config
from ges.catalog import utc_time
from ges.solar import solar_weights, sun_direction
from ges.atmosphere_scattering import ScatteringRenderer, geographic
from scripts.review_cloud_relief import review_camera, angles


def main():
    processed=load_config().processed_dir;source=processed/'cloud_relief_v1';out=processed/'cloud_relief_v3'
    out.mkdir(parents=True,exist_ok=True)
    meta=json.loads((source/'verification.json').read_text());samples={s['sample']:s for s in meta['samples']}
    records=[];twilight_panels=[];night_panels=[];overview=[]
    for name in ['goes17_1640','goes16_0640','goes16_0740','goes16_1640']:
        sample=samples[name];folder=source/name;dest=out/name;dest.mkdir(exist_ok=True)
        paths=[folder/n for n in ['independent_cloud.png','static_ground.png','retrieved_height.npz','height_support.png','observation_coverage.png']]
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        cloud=np.asarray(Image.open(paths[0]).convert('RGBA'));ground=np.asarray(Image.open(paths[1]).convert('RGB'))
        with np.load(paths[2]) as data:heights=data['height_km'].copy()
        h,w=heights.shape;lon=-180+(np.arange(w)+.5)*360/w;lat=90-(np.arange(h)+.5)*360/w
        stamp=utc_time(sample['source_utc']);sun=sun_direction(stamp)
        elevation=solar_weights(stamp,lon[None,:],lat[:,None]).elevation_deg
        cases=[]
        if name=='goes17_1640':
            for label,lower,upper in [('dawn_south',-30,-5),('dawn_north',5,40)]:
                valid=np.isfinite(heights)&(abs(elevation)<1)&(lat[:,None]>lower)&(lat[:,None]<upper)&(cloud[...,3]>50)
                if not valid.any():raise ValueError('No real cloudy height-supported terminator sample')
                score=np.where(valid,np.nan_to_num(heights)*cloud[...,3],-1)
                row,col=np.unravel_index(np.argmax(score),score.shape)
                target_lon,target_lat=float(lon[col]),float(lat[row])
                for side,offset in [('from_night',-14),('from_day',14)]:
                    p=geographic(target_lon+offset,target_lat,8871)
                    camera={'position':p,'target':geographic(target_lon,target_lat,6371),'up':p/np.linalg.norm(p),'fov':45}
                    cases.append((label+'_'+side,camera,target_lon,target_lat,float(elevation[row,col])))
        else:
            camera=review_camera(-85);target=camera['target']/6371
            lo=float(np.rad2deg(np.arctan2(target[1],target[0])));la=float(np.rad2deg(np.arcsin(target[2])))
            cases.append(('day_control' if name.endswith('1640') else 'night',camera,lo,la,
                          float(solar_weights(stamp,lo,la).elevation_deg)))
        renderer=ScatteringRenderer([ground]*3,1280,720,supersample=1.5,cloud_layer=(cloud,heights))
        for label,camera,lo,la,elev in cases:
            pair=[]
            for state,depth in [('before',0.),('night_depth',1.)]:
                pixels=renderer.render(camera,sun,steps=48,sun_steps=12,relief_strength=.4,night_depth_strength=depth)
                Image.fromarray(pixels).save(dest/(label+'_'+state+'.png'));pair.append(pixels)
            panel=Image.new('RGB',(2560,756),(10,14,22))
            for i,im in enumerate(pair):panel.paste(Image.fromarray(im),(1280*i,36))
            ImageDraw.Draw(panel).text((12,10),f'{name} | {stamp.isoformat()} | {label} | target sun {elev:+.2f} deg | LEFT previous / RIGHT night depth',fill='white')
            panel.save(dest/(label+'_comparison.png'))
            if name=='goes17_1640':twilight_panels.append(panel)
            elif label=='night':night_panels.append(panel)
            if label in ['dawn_south_from_night','night','day_control']:
                overview.append((name+' '+label,pair[1]))
            delta=abs(pair[1].astype(np.int16)-pair[0].astype(np.int16))
            if label=='day_control':np.testing.assert_array_equal(pair[0],pair[1])
            records.append({'sample':name,'view':label,'actual_scan_start_utc':sample['source_utc'],
                'camera':{k:np.asarray(v).tolist() for k,v in camera.items()},**angles(camera),
                'target_longitude':lo,'target_latitude':la,'target_solar_elevation_deg':elev,
                'mean_display_difference_dn':float(delta.mean()),'p99_display_difference_dn':float(np.quantile(delta,.99)),
                'source_directory':str(folder.resolve()),'source_sha256_unchanged':hashes})
            print('DONE',name,label,'sun elevation',round(elev,3),'mean delta',round(float(delta.mean()),4),flush=True)
        renderer.close()
        for p in paths:assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[p.name]
    for filename,panels in [('twilight_comparison.png',twilight_panels),('night_comparison.png',night_panels)]:
        sheet=Image.new('RGB',(2560,756*len(panels)))
        for i,p in enumerate(panels):sheet.paste(p,(0,i*756))
        sheet.save(out/filename)
    sheet=Image.new('RGB',(1280,756*len(overview)),(10,14,22));draw=ImageDraw.Draw(sheet)
    for i,(label,pixels) in enumerate(overview):
        draw.text((12,i*756+10),label+' | actual UTC | night depth on',fill='white');sheet.paste(Image.fromarray(pixels),(0,i*756+36))
    sheet.save(out/'overview.png')
    report={'recipe':'night-only-height-normal-display-v3','geometry_strength_unchanged':.4,
            'night_depth_strength':1.,'night_cue_max_linear_fraction':.18,
            'night_key_fixed_ecef':[.4,-.6,.7],'key_is_illustrative_not_physical_light':True,
            'solar_gate':'1-C2(sin(elevation),sin(-6deg),sin(+6deg)); full at -6deg, exactly off at +6deg',
            'display_only':'Height-normal brightness cue, NOT sunlight, moonlight, new cloud thickness or IR radiance measurement; hue/alpha and source files unchanged',
            'twilight':'Actual GOES17 2020-10-29 16:40 scan, sunrise; camera aims at real supported cloudy cells within 1deg of terminator. No fabricated sunset or moved solar time.',
            'controls':'Same geometry/camera/UTC/atmosphere on both sides, only night_depth_strength changes. Day control exact.',
            'new_downloads':False,'samples':records,'limits':'v1/v2 coarse heights and height-field limitations remain; static views do not validate continuous weather playback. Not Blender integration.'}
    (out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>晨昏线与夜间云层立体感</title>
<style>body{background:#0b1019;color:#dbe7f5;margin:24px;font:16px system-ui}img{width:100%}a{color:#9cd8ff}</style>
<h1>真实晨昏线 / 夜间增强</h1><p>相同2500公里机位和40%云高显示。左侧原版，右侧夜间形状明暗增强；白天保持不变。增强是由实测高度支持的显示效果，不代表月光或新增红外观测。</p>
<h2>晨昏交界：GOES17实际2020-10-29 16:40 UTC扫描</h2><p>四行：南、北两处晨线云区，各从夜侧和日侧看。中心太阳高度在±1°内，太阳没有人为移动。</p>
<img src="twilight_comparison.png"><h2>真实夜间两时次</h2><img src="night_comparison.png">
<p>云高几何和透明度不变，夜侧线性光明暗修饰上限±18%，在太阳高度-6°到+6°平滑关闭。仍不是完整体积云或连续延时验收。</p>
<p><a href="verification.json">来源、UTC、太阳高度和验证</a></p>''',encoding='utf-8')
    print('REPORT',out/'index.html',flush=True)


if __name__=='__main__':main()
