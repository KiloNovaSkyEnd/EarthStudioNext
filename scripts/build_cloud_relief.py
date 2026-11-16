"""Cached real ABI height/material pilot; matched flat/subtle orbital views.

Run from project root: .venv/Scripts/python.exe -m scripts.build_cloud_relief
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from PIL import Image, ImageDraw
from ges.catalog import utc_time
from ges.cloud_relief import load_abi_height, separate_material, height_display
from ges.atmosphere_scattering import ScatteringRenderer, orbit_camera
from ges.film_transition import load_reference, daylight_display, smoother, cloud_day_weight
from ges.blend_night import linear_rgb, encode_rgb
from ges.solar import solar_weights, sun_direction
from ges.storage import load_config
from ges.download import read_manifest

ROOT = Path(__file__).resolve().parents[1]


def build(args):
    cfg = load_config(); folder = cfg.processed_dir/'cloud_relief_v1'; folder.mkdir(parents=True, exist_ok=True)
    baseline = cfg.processed_dir/'day_night_v9/earth_day_night.png'
    original_hash = hashlib.sha256(baseline.read_bytes()).hexdigest()
    meta = json.loads(baseline.with_suffix('.json').read_text())
    width = args.texture_width
    def read(path, mode='L', nearest=False):
        return np.asarray(Image.open(path).convert(mode).resize((width,width//2),
            Image.Resampling.NEAREST if nearest else Image.Resampling.BOX)).copy()
    dg, _ = load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',width,
                          'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    ng, _ = load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',width,
                          'static reference night-lights composite, not contemporaneous with satellite clouds')
    ng = np.maximum(ng,(4,5,12)).astype(np.uint8)
    samples = []
    for satellite in ['goes16','goes17']:
        record = next(s for s in meta['night_source']['sources'] if s['provenance']['satellite']==satellite)
        day = next(s for s in meta['day_sources'] if s['provenance']['satellite']==satellite)
        samples.append((satellite+'_1640',Path(record['image']),record['provenance'],Path(day['image'])))
    for hour in ['0640','0740']:
        p = cfg.processed_dir/f'validation_v9/goes16_{hour}/goes16_evidence_night.png'
        samples.append(('goes16_'+hour,p,json.loads(p.with_suffix('.json').read_text()),None))
    records=[]; panels=[]
    lon=-180+(np.arange(width)+.5)*360/width
    lat=90-(np.arange(width//2)+.5)*360/width
    for name, ir_path, m, vis_path in samples:
        out=folder/name;out.mkdir(exist_ok=True)
        stamp=utc_time(m['scan_start_utc']); sat=m['satellite']
        manifest=read_manifest(Path(m['source_l2_manifest']))
        heights,audit=load_abi_height(manifest['local_files'],width,sat,m['scan_start_utc'],m['scan_end_utc'])
        cls_path=Path(m['cloud_evidence_classes']);cls_path=cls_path if cls_path.is_absolute() else ir_path.parent/cls_path
        classes=read(cls_path,nearest=True);night=read(ir_path,'RGBA')
        coverage_path=Path(m['source_ir_coverage'])
        if not coverage_path.is_absolute():coverage_path=ir_path.parent/coverage_path
        coverage=read(coverage_path,nearest=True)>0
        if vis_path:
            vm=json.loads(vis_path.with_suffix('.json').read_text())
            if vm['product']!='measured-visible-cloud-display' or vm['satellite']!=sat or abs((utc_time(vm['scan_start_utc'])-stamp).total_seconds())>1:
                raise ValueError('Independent VIS must match exact source/scan')
            alpha=read(vis_path).astype(np.float32)/255
            cov=read(vis_path.parent/vm['coverage'],nearest=True)>0
        else:alpha=np.zeros(classes.shape,np.float32);cov=np.zeros(classes.shape,bool)
        solar=solar_weights(stamp,lon[None,:],lat[:,None])
        alpha,day_ground=daylight_display(alpha,dg,'sunlit-v1')
        night[~coverage]=0
        cloud=separate_material(alpha,cov,night,classes,cloud_day_weight(solar.elevation_deg,'solar-sine-c2'))
        ground_weight=smoother(solar.elevation_deg,-12,24)
        ground=encode_rgb(day_ground*ground_weight[...,None]+linear_rgb(ng)*(1-ground_weight[...,None]))
        heights=np.where(np.isin(classes,[2,3,5,6,7,8,9]),heights,np.nan)
        Image.fromarray(cloud).save(out/'independent_cloud.png')
        Image.fromarray(ground).save(out/'static_ground.png')
        Image.fromarray(np.isfinite(heights).astype(np.uint8)*255).save(out/'height_support.png')
        Image.fromarray(coverage.astype(np.uint8)*255).save(out/'observation_coverage.png')
        Image.fromarray((~coverage).astype(np.uint8)*255).save(out/'static_reference_only.png')
        np.savez_compressed(out/'retrieved_height.npz',height_km=heights)
        renderer=ScatteringRenderer([ground]*3,args.width,args.width*9//16,supersample=1.5,cloud_layer=(cloud,heights))
        views=[]
        # Nadir and grazing inspection at the same real acquisition time.
        from ges.atmosphere_scattering import geographic
        center=-85 if sat=='goes16' else -130
        for view,alt in [('nadir',1500),('oblique600',600),('oblique1500',1500)]:
            camera=orbit_camera(center,15,alt,heading=1)
            if view=='nadir':
                camera={'position':geographic(center,15,6371+alt),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':45}
            pair=[]
            for state,strength in [('flat',0.),('subtle',args.strength)]:
                image=renderer.render(camera,sun_direction(stamp),steps=48,sun_steps=12,relief_strength=strength)
                Image.fromarray(image).save(out/f'{view}_{state}.png');pair.append(image)
            delta=abs(pair[0].astype(np.int16)-pair[1].astype(np.int16))
            views.append({'view':view,'altitude_km':alt,'mean_delta_dn':float(delta.mean()),'p99_delta_dn':float(np.quantile(delta,.99))})
            if view=='oblique600':
                panel=Image.new('RGB',(args.width*2,args.width*9//16+32),(10,14,22))
                for i,im in enumerate(pair):panel.paste(Image.fromarray(im),(args.width*i,32))
                ImageDraw.Draw(panel).text((10,9),f'{name} | {stamp.isoformat()} | LEFT flat / RIGHT subtle {args.strength:.2f} | single sensor, missing clouds remain missing',fill='white')
                panel.save(out/'comparison.png');panels.append(panel)
        renderer.close()
        finite=heights[np.isfinite(heights)]
        record={'sample':name,'source_ir_image':str(ir_path),'source_vis_image':str(vis_path) if vis_path else None,
                'source_utc':stamp.isoformat(),'height_audit':audit,'height_supported_display_cells':int(np.isfinite(heights).sum()),
                'retrieved_max_km':float(finite.max()),'display_max_km':float(height_display(finite,args.strength).max()),
                'cloud_pixels_without_height':int(((cloud[...,3]>0)&~np.isfinite(heights)).sum()),'views':views}
        (out/'provenance.json').write_text(json.dumps(record,indent=2),encoding='utf-8');records.append(record)
        print('DONE',name,'height max',record['retrieved_max_km'],'display max',record['display_max_km'],flush=True)
    sheet=Image.new('RGB',(panels[0].width,sum(p.height for p in panels)))
    y=0
    for panel in panels:sheet.paste(panel,(0,y));y+=panel.height
    sheet.save(folder/'comparison.png')
    assert hashlib.sha256(baseline.read_bytes()).hexdigest()==original_hash
    report={'recipe':'independent-cloud-restrained-height-pilot-v1','strength':args.strength,
            'height_display':'0.3 km display shell + strength * delivered good-quality HT; unsupported stays 0.3km, no inferred height',
            'coverage_contract':'observation_coverage.png is original measured IR availability; independent_cloud.png alpha is display opacity, NEVER coverage; height_support.png is separate',
            'day_material':'Achromatic measured VIS display on static ground, NOT the accepted measured RGB film composite',
            'night_material':'Existing observed IR palette and opacity, restricted to original cloudy L2 classes; not optical thickness',
            'normal_cue':'differential normal only, maximum +/-4% linear light, daylight gated, no second global Lambert lighting',
            'baseline_sha256_unchanged':original_hash,'new_downloads':False,'polar_cloud_fill':False,'samples':records,
            'limits':'Research backend only, NOT Blender integration or global replacement. No cloud base/thickness, soft ground shadows or parallax correction. Height interpolation is display-only; coarse retrieval is not fine geometry. Two night acquisitions one hour apart are not a dense weather playback or temporal acceptance. Atmospheric path uses ground endpoint approximation. No full dusk sequence yet.'}
    (folder/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (folder/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>Subtle cloud relief pilot</title>
<style>body{background:#0b1019;color:#dbe7f5;font:16px system-ui;margin:24px}img{width:100%}p{max-width:1000px}</style>
<h1>云层轻微起伏：左平面 / 右立体</h1><p>云高以压缩比例用于显示，参数见验证记录。地表与云独立；无高度云保留在0.3km显示层，不推算真实高度。日侧为实测可见光灰白显示，不替换原有RGB版本。</p>
<p>四行依次为 GOES16日侧、GOES17日侧、GOES16夜间06:40、07:40 UTC。两个夜间时次间隔一小时，尚非连续延时验收。未接入Blender；软投影、完整暮光与密集时间序列待验证。</p>
<img src="comparison.png"><p><a href="verification.json">数据来源和验证记录</a></p>''',encoding='utf-8')
    print('REPORT',folder/'index.html',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--width',type=int,default=960)
    parser.add_argument('--texture-width',type=int,default=4096);parser.add_argument('--strength',type=float,default=.35)
    args=parser.parse_args();height_display([1],args.strength);build(args)
