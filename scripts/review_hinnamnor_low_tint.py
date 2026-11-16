"""One-factor opt-in low-cloud tint review; all observations and legacy outputs read-only."""
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from ges.storage import load_config
from ges.catalog import utc_time
from ges.solar import sun_direction
from ges.goni_lowcloud import spectral_night_material,low_liquid_confidence
from ges.goni_film import NativeCloudRenderer
from ges.atmosphere_scattering import geographic
from ges.film_transition import load_reference
from scripts.compare_hinnamnor_geocolor import project,sha
from scripts.soften_goni_boundaries import inward_feather
from scripts.audit_render_baseline import difference


def locations():
    cfg=load_config()
    return cfg,cfg.processed_dir/'hinnamnor_low_tint_v1',cfg.processed_dir/'hinnamnor_geocolor_v1'


def material(stamp,checks_only=False):
    cfg,root,source=locations();src=source/stamp;dst=root/stamp
    if not checks_only:
        dst.mkdir(exist_ok=False)
        project(utc_time('2022-08-31T'+stamp[:2]+':'+stamp[2:]+':00Z'),dst,source=src,low_cloud_tint_strength=.85)
    # Compare the old source function itself, not an implementation-shaped oracle.
    spec=importlib.util.spec_from_file_location('ges._frozen_lowcloud',root/'source_before/ges/goni_lowcloud.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    with np.load(src/'observed_inputs.npz') as f:t,sw=f['B13'],f['B07']
    with np.load(src/'comparison_layers.npz') as f:
        p=f['B_probability'][::2,::2];low=f['B_low_confidence'][::2,::2]
        eligible=f['B_shortwave_eligible'][::2,::2];day=f['B_day_weight']
    low=low*inward_feather(low>0)
    old=legacy.spectral_night_material(t,sw,p,low,eligible)
    current=spectral_night_material(t,sw,p,low,eligible)
    new=spectral_night_material(t,sw,p,low,eligible,low_cloud_tint_strength=.85)
    for a,b in zip(old,current):assert np.array_equal(a,b),'Legacy function changed'
    assert np.array_equal(old[1],new[1]),'Night opacity changed'
    weights=np.array([.2126,.7152,.0722],np.float32)
    luma_error=float(np.max(abs(new[0]@weights-old[0]@weights)))
    chroma_error=float(np.max(abs((new[0][...,2]-new[0][...,0])-.85*(old[0][...,2]-old[0][...,0]))))
    assert luma_error<2e-7 and chroma_error<2e-7
    before=np.asarray(Image.open(src/'B_current_material_rgba.png').convert('RGBA'))
    after=np.asarray(Image.open(dst/'B_current_material_rgba.png').convert('RGBA'))
    assert np.array_equal(before[...,3],after[...,3]),'Blended material alpha changed'
    before_upload=np.asarray(Image.open(src/'B_current_upload_rgba.png'))
    after_upload=np.asarray(Image.open(dst/'B_current_upload_rgba.png'))
    assert np.array_equal(before_upload[...,3],after_upload[...,3]),'Uploaded alpha changed'
    changed=np.any(before[...,:3]!=after[...,:3],axis=-1)
    supported=np.repeat(np.repeat(low>0,2,0),2,1)
    assert not np.any(changed&(~supported|(day>=1)))
    assert np.array_equal(before[...,3]>0,after[...,3]>0)
    for name in ['A_day_weight','B_day_weight','B_low_evidence','B_shortwave_eligible']:
        assert sha(src/(name+'.png'))==sha(dst/(name+'.png')),name
    delta=np.abs(after[...,:3].astype(np.int16)-before[...,:3].astype(np.int16))
    Image.fromarray(np.minimum(delta*8,255).astype(np.uint8)).save(dst/'RGB_difference_x8.png')
    report={'nominal_utc':'2022-08-31T'+stamp[:2]+':'+stamp[2:]+':00Z',
            'strength':.85,'legacy_function_exact':True,'night_and_blended_and_uploaded_alpha_exact':True,
            'coverage_class_confidence_solar_gates_unchanged':True,'changed_rgb_pixels':int(changed.sum()),
            'changed_rgb_percent':float(changed.mean()*100),'rgb_max_delta_dn':int(delta.max()),
            'prequantization_display_luma_max_error':luma_error,'prequantization_chroma_scale_max_error':chroma_error,
            'classification_note':'Existing phase1/2 QF0 and height/confidence contract retained, not independently reclassified.'}
    (dst/'checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('MATERIAL PASS',stamp,report,flush=True)


def pair(path,left,right,title):
    sheet=Image.new('RGB',(left.shape[1]*2,left.shape[0]+30),'#0b1019')
    sheet.paste(Image.fromarray(left),(0,30));sheet.paste(Image.fromarray(right),(left.shape[1],30))
    ImageDraw.Draw(sheet).text((10,8),title+' | LEFT legacy / RIGHT tint0.85',fill='white');sheet.save(path)


def finalize():
    cfg,root,source=locations()
    assert not (root/'verification.json').exists(),'Choose a new output version instead of overwriting a completed review'
    day,_=load_reference(cfg.raw_dir/'reference/BlueMarble_200410_topography_8km.jpg',4096,
                         'static cloud-free ground reference, NOT 2020 observations or cloud coverage')
    night,_=load_reference(cfg.raw_dir/'reference/BlackMarble_2016_3km.jpg',4096,
                           'static reference night-lights composite, not contemporaneous with satellite clouds')
    water=np.asarray(Image.open(cfg.processed_dir/'cloud_relief_v4/static_ocean_mask.png').convert('L'))
    camera_set={
        'nadir':{'position':geographic(128,25,9371),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':38},
        'oblique':{'position':geographic(109,25,10571),'target':geographic(128,25,6371),'up':np.array([0.,0.,1.]),'fov':38},
        'detail':{'position':geographic(128,25,7971),'target':np.zeros(3),'up':np.array([0.,0.,1.]),'fov':32}}
    settings=dict(volume=True,atmosphere=True,airglow=True,height_scale=.4,thickness=.8,volume_samples=96)
    engine=NativeCloudRenderer(day,night,960,540,supersample=1.25,opacity_gamma=1.25,geometry_bridge_pixels=2,ocean_mask=water)
    render_checks=[];samples=[];inputs={}
    spec=importlib.util.spec_from_file_location('ges._frozen_lowcloud',root/'source_before/ges/goni_lowcloud.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    try:
        for stamp in ['0830','1000','1130']:
            src=source/stamp;dst=root/stamp
            samples.append(json.loads((dst/'checks.json').read_text()))
            meta=json.loads((src/'official_metadata.json').read_text())
            projection=meta['projection'].copy();projection['b']=projection['a']*(1-1/projection['rf'])
            metadata={'projection':projection,'extent_m':meta['area_extent_m']}
            with np.load(src/'l2_observed_roi.npz') as f:
                ht,err=f['CldTopHght'],f['ZcError']
                class_args=[f['CloudMask'],f['CloudMaskQualFlag'],f['CloudPhase'],f['CloudPhaseFlag'],ht/1000,err/1000,f['CloudHgtQF']]
                confidence=low_liquid_confidence(*class_args)
                assert np.array_equal(confidence,legacy.low_liquid_confidence(*class_args)),'L2 classification changed'
                samples[-1]['classification_full_native_rectangle_diagnostic']={
                    'strict':int((confidence==1).sum()),'partial':int((confidence==np.float32(.35)).sum()),
                    'not_supported_low':int((confidence==0).sum()),'legacy_exact':True,
                    'note':'Diagnostic before existing fixed ROI/join; candidate does not expand that ROI.'}
                good=np.isin(f['CloudMask'],[2,3])&(f['CloudMaskQualFlag']==0)&(f['CloudHgtQF']==0)
                good&=np.isfinite(ht)&(ht>0)&(ht<=20000)&np.isfinite(err)&(err>=0)&(err<=3000)
                height=np.where(good,ht/1000,np.nan).astype(np.float32)
            np.savez_compressed(dst/'fixed_height.npz',height_km=height)
            sun=sun_direction(utc_time(meta['nominal_utc']));renders={}
            for revision,folder in [('legacy',src),('tint085',dst)]:
                file=folder/'B_current_material_rgba.png';inputs[str(file.resolve())]=sha(file)
                rgba=np.asarray(Image.open(file).convert('RGBA'));engine.update(rgba,height,metadata)
                for label,camera in camera_set.items():
                    pixels=engine.render(camera,sun,**settings)
                    renders[revision,label]=pixels;Image.fromarray(pixels).save(dst/(revision+'_'+label+'.png'))
                if revision=='tint085':
                    assert np.array_equal(renders[revision,'oblique'],engine.render(camera_set['oblique'],sun,**settings))
                    for effect,override in [('atmosphere',{'atmosphere':False}),('airglow',{'airglow':False})]:
                        off=engine.render(camera_set['oblique'],sun,**{**settings,**override})
                        Image.fromarray(off).save(dst/('tint085_no_'+effect+'.png'))
                        d=difference(renders[revision,'oblique'],off)
                        if effect=='atmosphere' or stamp=='1130':assert d['max_dn']>0,(stamp,effect)
                        render_checks.append({'stamp':stamp,'effect':effect,**d})
            for label in camera_set:
                pair(dst/('render_'+label+'_pair.png'),renders['legacy',label],renders['tint085',label],stamp+' UTC '+label)
            for folder in [src,dst]:
                for name in ['observed_inputs.npz','l2_observed_roi.npz','official_layers.npz']:
                    path=folder/name
                    if path.exists():inputs[str(path.resolve())]=sha(path)
            # Same background, same opacity, same measured spatial texture.
            a=np.asarray(Image.open(src/'B_current_flat_preview.png').convert('RGB'))
            b=np.asarray(Image.open(dst/'B_current_flat_preview.png').convert('RGB'))
            pair(dst/'flat_pair.png',a,b,stamp+' UTC flat diagnostic (static night background)')
            print('RENDER PASS',stamp,flush=True)
        gpu=engine.device
    finally:engine.close()
    baseline=cfg.processed_dir/'audit_baseline_20261019/render_b'
    audit=root/'render_regression'
    original=json.loads((baseline/'verification.json').read_text())
    assert json.loads((audit/'verification.json').read_text())['repeat_exact']
    frozen={name:difference(np.asarray(Image.open(baseline/(name+'.png'))),np.asarray(Image.open(audit/(name+'.png'))))
            for name in original['output_sha256']}
    assert all(v['max_dn']==0 for v in frozen.values()),'Frozen renderer regression'
    before=json.loads((root/'before.json').read_text())
    assert all(Path(p).exists() and [Path(p).stat().st_size,Path(p).stat().st_mtime_ns]==v for p,v in before['protected'].items())
    allowed={'ges/goni_lowcloud.py','scripts/compare_hinnamnor_geocolor.py','tests/test_goni_lowcloud.py','docs/PROGRESS.md'}
    changed=[p for p,v in before['code'].items() if sha(p)!=v]
    assert all(Path(p).resolve().relative_to(Path.cwd()).as_posix() in allowed for p in changed),changed
    record={'samples':samples,'render_controls':render_checks,'gpu':gpu,'resolution':[960,540],
            'cameras':{k:{n:np.asarray(v).tolist() for n,v in c.items()} for k,c in camera_set.items()},'settings':settings,
            'input_sha256':inputs,'frozen_render_pixel_comparison':frozen,'old_data_files_preserved':len(before['protected']),
            'changed_existing_files':changed,'production_default_strength':1.,'candidate_strength':.85,
            'limits':'Tint only, explicit opt-in; classification, fixed ROI, density, seams and side-view stretching not fixed. '
                     'Three acquisitions, no temporal continuity acceptance; static ocean not a sea-state observation. '
                     'Same retrieved heights plus existing model column geometry, not recovered cloud interiors.'}
    (root/'verification.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    page='<meta charset="utf-8"><title>Hinnamnor low-cloud tint candidate</title><style>body{background:#0b1019;color:white;font:16px system-ui;margin:24px}img{max-width:100%}a{color:#9ed9ff}</style>'
    page+='<h1>Low-cloud tint: legacy 1.00 / candidate 0.85</h1><p>Only colour chroma changes. Alpha, measured coverage, L2 confidence and solar gates unchanged. Default stays legacy. No noise or generated cloud details. All times UTC.</p>'
    page+='<p><a href="../../../docs/HINNAMNOR_LOW_TINT_V1.md">Chinese report</a> | <a href="verification.json">Verification</a></p>'
    for stamp in ['0830','1000','1130']:
        page+='<h2>2022-08-31 '+stamp+' UTC</h2>'
        for name in ['flat_pair.png','render_nadir_pair.png','render_oblique_pair.png','render_detail_pair.png']:
            page+='<img src="'+stamp+'/'+name+'">'
    (root/'index.html').write_text(page,encoding='utf-8')
    print('REVIEW PASS; frozen images',len(frozen),'protected files',len(before['protected']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stamp',choices=['0830','1000','1130']);parser.add_argument('--finalize',action='store_true')
    parser.add_argument('--checks-only',action='store_true',help='Verify existing partial candidate without regenerating material')
    args=parser.parse_args()
    if args.stamp:material(args.stamp,args.checks_only)
    elif args.finalize:finalize()
    else:parser.error('Choose --stamp or --finalize')
