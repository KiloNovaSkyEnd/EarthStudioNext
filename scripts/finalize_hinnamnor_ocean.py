"""Measure ocean ablations, preserve reference provenance and seal short-pilot QA."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from ges.storage import load_config
from ges.solar import sun_direction
from ges.catalog import utc_time
from ges.atmosphere_scattering import camera_basis
from ges.goni_film import native_project
from scripts.review_hinnamnor_ocean import resources,frame,camera,SETTINGS,pair,STAMPS
from scripts.audit_render_baseline import difference
from scripts.compare_hinnamnor_geocolor import sha


def controls():
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_ocean_v1';out=root/'candidate_controls';out.mkdir(exist_ok=False)
    engine=resources(1280,720);cam=camera(True);results=[]
    try:
        for stamp in ['0830','1130']:
            rgba,h,meta,obs,src=frame(stamp,True);engine.update(rgba,h,meta);sun=sun_direction(utc_time(obs['nominal_utc']))
            on=engine.render(cam,sun,**SETTINGS,deep_ocean_material=True);Image.fromarray(on).save(out/(stamp+'_on.png'))
            for effect,override in [('atmosphere',{'atmosphere':False}),('airglow',{'airglow':False}),('city_lights',{'city_lights':False})]:
                off=engine.render(cam,sun,**{**SETTINGS,**override},deep_ocean_material=True)
                pair(out/(stamp+'_'+effect+'_pair.png'),off,on,stamp+' UTC candidate | LEFT '+effect+' OFF / RIGHT ON')
                d=difference(on,off)
                if stamp=='1130' or effect=='atmosphere':assert d['max_dn']>0,(stamp,effect)
                results.append({'stamp':stamp,'effect':effect,**d})
        gpu=engine.device
    finally:engine.close()
    # Surface-referenced clear-water screen mask; cloud rays can still intersect
    # neighboring elevated columns, so this is a diagnostic proxy, not truth.
    width,height=1280,720;right,up,forward=camera_basis(cam['position'],cam['target'],cam['up'])
    yy,xx=np.indices((height,width));sx=(2*(xx+.5)-width)/height;sy=(height-2*(yy+.5))/height
    ray=forward+np.tan(np.deg2rad(cam['fov']/2))*(sx[...,None]*right+sy[...,None]*up)
    ray/=np.linalg.norm(ray,axis=-1,keepdims=True);pos=np.asarray(cam['position']);b=ray@pos;q=b*b-pos@pos+6371**2
    hit=(q>=0);dist=-b-np.sqrt(np.maximum(q,0));hit&=dist>0;point=pos+ray*dist[...,None]
    normal=point/np.linalg.norm(point,axis=-1,keepdims=True)
    lo=np.rad2deg(np.arctan2(normal[...,1],normal[...,0]));la=np.rad2deg(np.arcsin(np.clip(normal[...,2],-1,1)))
    water=np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    wx=np.clip(((lo/360+.5)*water.shape[1]).astype(int),0,water.shape[1]-1);wy=np.clip(((.5-la/180)*water.shape[0]).astype(int),0,water.shape[0]-1)
    ocean=hit&(water[wy,wx]>250)&((-normal*ray).sum(-1)>.3)
    metrics=[]
    for stamp in ['0830','1000','1130']:
        rgba,h,meta,obs,src=frame(stamp,True);x,y=native_project(lo,la,meta['projection']);xmin,ymin,xmax,ymax=meta['extent_m']
        u=(x-xmin)/(xmax-xmin);v=(ymax-y)/(ymax-ymin);inside=np.isfinite(u)&np.isfinite(v)&(u>0)&(u<1)&(v>0)&(v<1)
        ix=np.clip((np.nan_to_num(u)*rgba.shape[1]).astype(int),0,rgba.shape[1]-1);iy=np.clip((np.nan_to_num(v)*rgba.shape[0]).astype(int),0,rgba.shape[0]-1)
        mask=ocean&inside&(rgba[iy,ix,3]<=13);assert mask.sum()>0
        Image.fromarray((mask*255).astype(np.uint8)).save(out/(stamp+'_surface_clear_water_proxy.png'))
        cases={}
        for name in ['legacy','candidate','no_clouds','no_atmosphere','no_reflections','no_airglow','no_lights','exposure_075','clear_no_atmosphere','clear_candidate_no_atmosphere']:
            a=np.asarray(Image.open(root/'diagnostics'/(stamp+'_'+name+'.png')).convert('RGB'),float)
            rgb=a[mask].mean(0);cases[name]={'mean_display_rgb_dn':rgb.tolist(),'mean_B_minus_R_dn':float(rgb[2]-rgb[0]),
                'weighted_display_brightness_dn':float(rgb@np.array([.2126,.7152,.0722]))}
        metrics.append({'utc':obs['nominal_utc'],'surface_clear_water_proxy_pixels':int(mask.sum()),'cases':cases})
    (out/'verification.json').write_text(json.dumps({'gpu':gpu,'component_controls':results,'ocean_proxy_metrics':metrics,
        'mask_definition':'Hit sea sphere, static water>250/255, view cosine>.3, inside AHI crop, nearest material alpha<=13/255. Surface proxy, not a verified cloud-free footprint.'},indent=2),encoding='utf-8')
    print('CANDIDATE CONTROLS PASS',flush=True)


def finalize():
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_ocean_v1';assert not (root/'verification.json').exists()
    movie=json.loads((root/'video/verification.json').read_text());assert len(movie['samples'])==7 and movie['real_acquisitions']==7
    sheet=Image.new('RGB',(1920,1176),'#0b1019');draw=ImageDraw.Draw(sheet)
    for i,stamp in enumerate(STAMPS):
        tile=Image.open(root/'video'/(stamp+'_candidate_4k.png')).convert('RGB').resize((640,360),Image.Resampling.LANCZOS)
        x,y=(i%3)*640,(i//3)*392;sheet.paste(tile,(x,y+28))
        draw.text((x+12,y+8),'2022-08-31 '+stamp[:2]+':'+stamp[2:]+' UTC | actual observation',fill='white')
    sheet.save(root/'video/contact_sheet.png')
    baseline=cfg.processed_dir/'audit_baseline_20261019/render_b';old=json.loads((baseline/'verification.json').read_text())
    diffs={name:difference(np.asarray(Image.open(baseline/(name+'.png'))),np.asarray(Image.open(root/'render_regression'/(name+'.png')))) for name in old['output_sha256']}
    assert all(v['max_dn']==0 for v in diffs.values()),'Default render regression'
    before=json.loads((root/'before.json').read_text());protected={p:v for p,v in before['protected'].items() if not any(n in Path(p).parts for n in ['hinnamnor_ocean_v1','hinnamnor_ocean_l2_ranges'])}
    assert all(Path(p).exists() and [Path(p).stat().st_size,Path(p).stat().st_mtime_ns]==v for p,v in protected.items())
    allow={'ges/goni_film.py','ges/shaders/goni_film.frag','scripts/compare_hinnamnor_geocolor.py','scripts/read_hinnamnor_geocolor_l2.py','docs/PROGRESS.md'}
    changed=[p for p,v in before['code'].items() if sha(p)!=v]
    assert all(Path(p).resolve().relative_to(Path.cwd()).as_posix() in allow for p in changed),changed
    # Original verified backups are SHA-identical to the pre-change files.
    for p in (root/'source_before_verified').rglob('*'):
        if p.is_file():assert sha(p)==before['code'][str(Path.cwd()/p.relative_to(root/'source_before_verified'))]
    hsd=sum(p.stat().st_size for p in (cfg.raw_dir/'hinnamnor_ocean_v1').rglob('*.DAT.bz2'))
    ranges=sum(p.stat().st_size for p in (cfg.raw_dir/'hinnamnor_ocean_l2_ranges').rglob('*.bin'))
    plan=json.loads((root/'download_plan.json').read_text());assert hsd==plan['hsd_bytes'] and hsd+ranges<=plan['batch_ceiling_bytes']
    # Reference is explicitly qualitative: different time/view, no pixel score.
    inv=json.loads((cfg.processed_dir/'hinnamnor_research_20261019/media/media_inventory.json').read_text(encoding='utf-8'))
    refdir=root/'reference_comparison';refdir.mkdir(exist_ok=False);refs=[]
    for index,stamp in [(6,'0930'),(13,'1030')]:
        ref=inv['stills'][index];path=Path(ref['file']);assert sha(path)==ref['sha256']
        original=Image.open(path).convert('RGB');original.thumbnail((1920,1080))
        current=Image.open(root/'video'/(stamp+'_candidate_4k.png')).convert('RGB').resize((1920,1080),Image.Resampling.LANCZOS)
        pair(refdir/(stamp+'_qualitative.png'),np.asarray(original),np.asarray(current),
             'LEFT local SDK reference / RIGHT candidate | different acquisition and view: qualitative only')
        refs.append({'reference':ref,'candidate_utc':stamp,'pixel_metric':None})
    (refdir/'provenance.json').write_text(json.dumps(refs,indent=2),encoding='utf-8')
    result={'frozen_baseline_40_images':diffs,'old_files_preserved_size_mtime':len(protected),'changed_existing_files':changed,
            'hsd_new_bytes':hsd,'l2_range_new_bytes':ranges,'actual_satellite_payload_bytes':hsd+ranges,
            'planned_maximum_bytes':plan['batch_ceiling_bytes'],'new_unique_scans':6,'reused_unique_scans':1,
            'production_default_ocean_candidate':False,'visual_acceptance':'Pending human review; full window not started',
            'movie_verification':'video/verification.json','component_and_ocean_metrics':'candidate_controls/verification.json',
            'limits':'Metadata preservation is not a full old-archive content hash. Retained missing source pixels, no weather interpolation, 4K output is not 4K satellite resolution.'}
    (root/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    page='<meta charset="utf-8"><title>Hinnamnor ocean and twilight pilot</title><style>body{background:#0b1019;color:#dfeaf7;font:16px system-ui;margin:24px}img,video{max-width:100%}a{color:#9ed9ff}</style>'
    page+='<h1>Ocean material / observed twilight: review candidate</h1><p>2022-08-31 09:30–10:30 UTC, seven actual AHI scans at 10-minute cadence. 24 held display frames per observation; no weather interpolation. Camera/exposure fixed. Production defaults unchanged. Full window awaits visual acceptance.</p>'
    page+='<p><a href="../../../docs/HINNAMNOR_OCEAN_VIDEO_V1.md">Chinese quality report</a> | <a href="verification.json">Verification</a></p>'
    page+='<p>Visual acceptance is pending. Existing source-region edges, eye-wall stripes and 10-minute sampling jumps remain review issues.</p><img src="video/contact_sheet.png">'
    for name,title in [('AB_1080p','Side by side: legacy / candidate; each half 1920x1080'),('legacy_4k','Legacy 3840x2160'),('candidate_4k','Candidate 3840x2160')]:
        page+='<h2>'+title+'</h2><video controls preload="metadata" src="video/'+name+'.mp4"></video>'
    for stamp in ['0830','1130']:
        for effect in ['atmosphere','airglow','city_lights']:
            page+='<h2>'+stamp+' '+effect+' OFF / ON</h2><img src="candidate_controls/'+stamp+'_'+effect+'_pair.png">'
    for stamp in ['0830','1000','1130']:
        page+='<h2>'+stamp+' ocean old / candidate</h2><img src="diagnostics/'+stamp+'_candidate_pair.png">'
    for stamp in ['0930','1030']:page+='<h2>Qualitative reference, different time and view</h2><img src="reference_comparison/'+stamp+'_qualitative.png">'
    (root/'index.html').write_text(page,encoding='utf-8')
    print('FINAL QA PASS',hsd+ranges,'bytes;',len(protected),'old files;40 baseline images exact',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--controls',action='store_true');a=p.parse_args()
    controls() if a.controls else finalize()
