"""Isolate cloud footprints, static water material and explicit airglow toggles."""
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from ges.storage import load_config
from ges.atmosphere_scattering import ScatteringRenderer
from ges.catalog import utc_time
from ges.solar import sun_direction, solar_weights
from ges.film_transition import load_reference, cloud_day_weight
from ges.cloud_relief import separate_material
from scripts.prepare_ocean_reference import fetch_land, ocean_mask


def full_cloud_material(cfg,out):
    baseline=json.loads((cfg.processed_dir/'cloud_relief_v1/verification.json').read_text())
    sample=next(s for s in baseline['samples'] if s['sample']=='goes17_1640')
    ir_path=Path(sample['source_ir_image'])
    vis_path=Path(sample['source_vis_image'])
    m=json.loads(ir_path.with_suffix('.json').read_text());vm=json.loads(vis_path.with_suffix('.json').read_text())
    if vm['satellite']!='goes17' or abs((utc_time(vm['scan_start_utc'])-utc_time(sample['source_utc'])).total_seconds())>1:
        raise ValueError('Full-resolution VIS scan mismatch')
    cls_path=Path(m['cloud_evidence_classes'])
    if not cls_path.is_absolute():cls_path=ir_path.parent/cls_path
    paths=[ir_path,vis_path,cls_path,vis_path.parent/vm['coverage'],ir_path.parent/m['source_ir_coverage']]
    hashes={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    night=np.asarray(Image.open(ir_path).convert('RGBA')).copy()
    alpha=np.asarray(Image.open(vis_path).convert('L'),np.float32)/255
    classes=np.asarray(Image.open(cls_path));cov=np.asarray(Image.open(paths[3]))>0;ir_cov=np.asarray(Image.open(paths[4]))>0
    h,w=classes.shape
    if (w,h)!=(8192,4096) or night.shape!=(h,w,4) or alpha.shape!=(h,w) or cov.shape!=(h,w):
        raise ValueError('Original full 8192x4096 cached inputs required; no upscaling')
    cloud=np.zeros_like(night);lon=-180+(np.arange(w)+.5)*360/w
    for row in range(0,h,128):
        sl=slice(row,min(row+128,h));lat=90-(np.arange(sl.start,sl.stop)+.5)*360/w
        a=alpha[sl];a=a+.65*a*(1-a)
        n=night[sl].copy();n[~ir_cov[sl]]=0
        e=solar_weights(utc_time(sample['source_utc']),lon[None,:],lat[:,None]).elevation_deg
        cloud[sl]=separate_material(a,cov[sl],n,classes[sl],cloud_day_weight(e,'solar-sine-c2'))
    Image.fromarray(cloud).save(out/'independent_cloud_8192.png')
    for p in paths:assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p.resolve())]
    return cloud,{'input_sha256_unchanged':hashes,'dimensions':[w,h],
                  'mapping':'Original cached 8192 grid, no upscaling or sharpening; same v1 cloud recipe; heights remain separate4096 grid.'}


def main():
    cfg=load_config();source=cfg.processed_dir/'cloud_relief_v3';out=cfg.processed_dir/'cloud_relief_v4'
    out.mkdir(parents=True,exist_ok=True);old=json.loads((source/'verification.json').read_text())
    land,land_meta=fetch_land();water=ocean_mask(land,4096);Image.fromarray(water).save(out/'static_ocean_mask.png')
    day,day_meta=load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',4096,
                               'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night,night_meta=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',4096,
                                   'static reference night-lights composite, not contemporaneous with satellite clouds')
    records=[];panels=[];air_panels=[];flat_panels=[]
    folder=cfg.processed_dir/'cloud_relief_v1/goes17_1640'
    paths=[folder/n for n in ['independent_cloud.png','static_ground.png','retrieved_height.npz','height_support.png','observation_coverage.png']]
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    cloud=np.asarray(Image.open(paths[0]).convert('RGBA'));ground=np.asarray(Image.open(paths[1]).convert('RGB'))
    with np.load(paths[2]) as f:heights=f['height_km'].copy()
    full_cloud,full_audit=full_cloud_material(cfg,out)
    print('RESTORED original8192 cloud material; keeping4096 height grid',flush=True)
    legacy_renderer=ScatteringRenderer([ground,day,night],1280,720,supersample=1.5,cloud_layer=(cloud,heights),ocean_mask=water)
    legacy_images={}
    for record in old['samples']:
        if record['sample']!='goes17_1640':continue
        camera={k:np.asarray(v) if k!='fov' else v for k,v in record['camera'].items()}
        sun=sun_direction(utc_time(record['actual_scan_start_utc']))
        # Use the actual user-reviewed PNG as baseline, not a recompiled legacy
        # branch whose derivatives can change under different shader control flow.
        original=source/'goes17_1640'/(record['view']+'_night_depth.png')
        legacy_images[record['view']]={'v3_legacy':np.asarray(Image.open(original).convert('RGB'))}
        for label,stable in [('sampling_only',True)]:
            legacy_images[record['view']][label]=legacy_renderer.render(camera,sun,steps=96,sun_steps=20,
                relief_strength=.4,night_depth_strength=1.,stable_cloud_sampling=stable)
    legacy_renderer.close()
    renderer=ScatteringRenderer([ground,day,night],1280,720,supersample=1.5,cloud_layer=(full_cloud,heights),ocean_mask=water)
    for record in old['samples']:
        if record['sample']!='goes17_1640':continue
        label=record['view'];dest=out/label;dest.mkdir(exist_ok=True)
        camera={k:np.asarray(v) if k!='fov' else v for k,v in record['camera'].items()}
        sun=sun_direction(utc_time(record['actual_scan_start_utc']));images=legacy_images[label].copy()
        for name,pixels in images.items():Image.fromarray(pixels).save(dest/(name+'.png'))
        cases=[('full_cloud_detail',True,False,False,.4,3.,renderer),('water_no_glow',True,True,False,.4,3.,renderer),
               ('lower_haze',True,True,False,.4,2.,renderer),('corrected',True,True,True,.4,2.,renderer),
               ('flat_control',True,True,True,0.,2.,renderer)]
        for name,stable,ocean,glow,strength,exposure,engine in cases:
            pixels=engine.render(camera,sun,steps=96,sun_steps=20,relief_strength=strength,night_depth_strength=1.,
                                   stable_cloud_sampling=stable,ocean_material=ocean,airglow=glow,exposure=exposure)
            Image.fromarray(pixels).save(dest/(name+'.png'));images[name]=pixels
        def pair(a,b,title):
            sheet=Image.new('RGB',(2560,756),(10,14,22))
            sheet.paste(Image.fromarray(images[a]),(0,36));sheet.paste(Image.fromarray(images[b]),(1280,36))
            ImageDraw.Draw(sheet).text((12,10),label+' | actual UTC '+record['actual_scan_start_utc']+' | '+title,fill='white')
            return sheet
        p=pair('v3_legacy','corrected','LEFT old rendering / RIGHT stable footprint + water material + airglow ON')
        p.save(dest/'before_after.png');panels.append(p)
        p=pair('lower_haze','corrected','SAME material/camera | LEFT airglow OFF / RIGHT airglow ON')
        p.save(dest/'airglow_toggle.png');air_panels.append(p)
        p=pair('flat_control','corrected','SAME water/airglow/sampling | LEFT flat / RIGHT 0.40 height')
        p.save(dest/'height_diagnostic.png');flat_panels.append(p)
        differences={}
        for a,b in [('v3_legacy','sampling_only'),('sampling_only','full_cloud_detail'),('full_cloud_detail','water_no_glow'),
                    ('water_no_glow','lower_haze'),('lower_haze','corrected'),('flat_control','corrected')]:
            d=abs(images[a].astype(np.int16)-images[b].astype(np.int16))
            differences[a+' -> '+b]={'mean_dn':float(d.mean()),'p99_dn':float(np.quantile(d,.99)),'max_dn':int(d.max())}
        assert np.any(images['corrected']!=images['lower_haze']), 'Airglow toggle has no rendered contribution'
        records.append({**record,'component_differences':differences})
        print('DONE',label,differences,flush=True)
    renderer.close()
    for p in paths:assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[p.name]
    for name,rows in [('before_after.png',panels),('airglow_toggle.png',air_panels),('height_diagnostic.png',flat_panels)]:
        sheet=Image.new('RGB',(2560,756*len(rows)))
        for i,row in enumerate(rows):sheet.paste(row,(0,i*756))
        sheet.save(out/name)
    report={'recipe':'twilight-rendering-audit-v4','source_sha256_unchanged':hashes,
            'confirmed_v3_airglow_enabled':False,'v4_airglow_enabled':True,'airglow_gain':1.,
            'cloud_sampling':'Analytic ray differentials on a local radial tangent plane; no derivative inflation from height discontinuity. Original cloud pixels/support unchanged.',
            'comparison_baseline':'Actual saved v3 night_depth PNG,48/12 integration; v4 component renders96/20. First baseline-to-sampling step also changes quadrature, not a pure sampling-only attribution.',
            'cloud_full_grid':full_audit,'scattering_display_exposure':2.,'prior_scattering_display_exposure':3.,
            'water_material':'Static geographic land-complement mask, two-pixel coastal exclusion, reference-colour directional diffuse + GGX sun reflection (roughness0.32,F0=0.0204), with solar-path attenuation; unmodified static night reference on water. No invented wave texture or wind observation.',
            'water_reference':land_meta,'day_reference':day_meta,'night_reference':night_meta,
            'height_strength':.4,'night_display_depth':1.,'integration_samples':[96,20],'samples':records,
            'limits':'Reference-based water material, no measured sea state, sky environment reflection or multiple scattering. Clouds still a coarse top-height field and8192-wide material with separate4096 height grid, not volume; true source filaments and perspective compression remain. No claim of eliminating all streaking. Airglow is approximate volume emission, not measured.'}
    (out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>晨线渲染问题核查</title>
<style>body{background:#0b1019;color:#dbe7f5;font:16px system-ui;margin:24px}img{width:100%}a{color:#9cd8ff}</style>
<h1>海面、云纹理采样与气辉：同机位对照</h1><p>左旧渲染，右为稳定采样、恢复已有8192网格云材质、独立海面受光/反射、减轻蓝雾和明确开启气辉。未补画云或提高云高。</p>
<img src="before_after.png"><h2>气辉开关分项检查</h2><p>之前整组气辉关闭；此处左关右开。昼侧蓝边来自散射，夜间气辉是独立的近似体发光，并非连续等亮的屏幕描边。</p>
<img src="airglow_toggle.png"><h2>平面/起伏诊断</h2><p>左平面右40%高度，其他相同。仍可见的长条结构不能简单归因于高度；原始纹理、粗网格和透视仍有限制。</p>
<img src="height_diagnostic.png"><p>海面为参考材质与固定粗糙度模型，没有新增海况观测、生成波浪或补画云。未宣称最终真实感通过。</p>
<p><a href="verification.json">逐项差异和来源</a> · <a href="https://www.naturalearthdata.com/downloads/50m-physical-vectors/50m-land/">Natural Earth静态海陆参考</a></p>''',encoding='utf-8')
    print('REPORT',out/'index.html',flush=True)


if __name__=='__main__':main()
