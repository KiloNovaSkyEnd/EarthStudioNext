"""Seal bounded cloud/lights/ocean review, independent controls and old-data preservation."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from ges.storage import load_config
from ges.catalog import utc_time
from ges.solar import sun_direction
from scripts.review_hinnamnor_targeted import engine,expanded
from scripts.review_hinnamnor_ocean import camera,SETTINGS,pair
from scripts.compare_hinnamnor_geocolor import sha


def main():
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_targeted_v1'
    assert not (root/'verification.json').exists(),'Do not overwrite a completed review'
    out=root/'details';out.mkdir(exist_ok=True)
    clouds=json.loads((root/'render_screened/verification.json').read_text())
    lights=json.loads((root/'lights_sea_same_gpu/verification.json').read_text())
    regression=json.loads((root/'same_gpu_comparison.json').read_text())
    assert len(clouds)==2 and all(c['colour_only_alpha_exact'] and c['tint_outside_low_support_changed']==0 for c in clouds)
    assert all(d['max_dn']==0 for d in regression['differences'].values())
    for record in clouds:
        assert record['gpu']==regression['gpu']
        assert all(record[k+'_contribution']['max_dn']>0 for k in ['atmosphere','airglow','city_lights'])
    assert lights['control_gpus']==[regression['gpu']]*2
    assert 'Ran 195 tests' in (root/'tests_verified.txt').read_text() and '\nOK' in (root/'tests_verified.txt').read_text()
    audits=[]
    for stamp in ['1000','1130']:
        src=root/stamp;meta=json.loads((src/'screened_candidate/material_metadata.json').read_text())
        assert all(v['valid_cloud_pixels_unchanged']>0 for v in meta['clear_screen_checks'].values())
        with np.load(src/'l2_observed_roi.npz') as f:
            mask=f['CloudMask'];phase=f['CloudPhase'];prob=f['CloudProbability'];
            Image.fromarray(np.rint(np.clip(prob,0,1)*255).astype(np.uint8)).save(out/(stamp+'_delivered_probability.png'))
            palette=np.array([[0,0,0],[70,85,100],[145,180,205],[235,245,255]],np.uint8)
            Image.fromarray(palette[np.clip(mask,0,3).astype(int)]).save(out/(stamp+'_delivered_mask.png'))
            Image.fromarray(np.clip(phase*50,0,255).astype(np.uint8)).save(out/(stamp+'_delivered_phase.png'))
        if stamp=='1130':
            old=np.asarray(Image.open(src/'expanded_legacy/B_current_material_rgba.png'))
            new=np.asarray(Image.open(src/'screened_candidate/B_current_material_rgba.png'))
            def flatten(a):
                alpha=a[...,3:4].astype(np.float32)/255
                return np.rint(a[...,:3]*alpha+np.array([10,15,25])*(1-alpha)).astype(np.uint8)
            # Native ROI switch lies at row1200/column1600; no resizing of the
            # measured texture, only exact crops for diagnosing that boundary.
            box=(700,560,1500,1260)
            a=np.asarray(Image.fromarray(flatten(old)).crop(box));b=np.asarray(Image.fromarray(flatten(new)).crop(box))
            pair(out/'internal_roi_crop.png',a,b,'Native-grid crop around old row1200/column1600 | old ROI / uniform evidence + clear screen')
        schema=json.loads((src/'l2_schema.json').read_text());audits.extend(schema)
    # Integrated illustration follows the already separate tests. It is not a
    # single-variable score because cloud scope, source resolution and gain differ.
    r=engine(3840,2160,13500);src,h,m,obs=expanded('1130')
    try:
        rgba=np.asarray(Image.open(src/'screened_candidate/B_current_material_rgba.png'))
        r.update(rgba,h,m);im=r.render(camera(),sun_direction(utc_time(obs['nominal_utc'])),**SETTINGS,city_light_gain=1.)
        Image.fromarray(im).save(out/'combined_screened_4k.png')
        integrated_gpu=r.device
    finally:r.close()
    plan=json.loads((root/'download_plan.json').read_text());hsd=json.loads((root/'hsd_download.json').read_text())
    assert sum(v['bytes'] for v in hsd)==plan['new_hsd_bytes'] and all(sha(v['local_file'])==v['sha256'] for v in hsd)
    range_total=sum(p.stat().st_size for p in (cfg.raw_dir/'hinnamnor_targeted_l2_ranges').rglob('*.bin'))
    range_new=sum(v['range_audit']['new_bytes_this_run'] for v in audits)
    assert plan['new_hsd_bytes']+range_total<=plan['maximum_archived_batch_bytes']
    protected=json.loads((root/'protected_before.json').read_text())
    assert all(Path(p).exists() and [Path(p).stat().st_size,Path(p).stat().st_mtime_ns]==v for p,v in protected.items())
    before=json.loads((root/'source_before.json').read_text())
    allow={'ges/goni_lowcloud.py','ges/goni_film.py','ges/shaders/goni_film.frag','scripts/compare_hinnamnor_geocolor.py',
           'scripts/read_hinnamnor_geocolor_l2.py','tests/test_native_ocean.py','docs/PROGRESS.md'}
    changed=[p for p,v in before.items() if sha(p)!=v]
    assert all(Path(p).relative_to(Path.cwd()).as_posix() in allow for p in changed),changed
    for p in (root/'source_before').rglob('*'):
        if p.is_file() and p.suffix in {'.py','.frag'}:assert sha(p)==before[str(Path.cwd()/p.relative_to(root/'source_before'))]
    result={'clouds':clouds,'lights_and_sea':lights,'same_gpu_default_comparison':regression,
            'integrated_gpu':integrated_gpu,'historical_gpu_comparison':'historical_gpu_comparison.json',
            'tests':{'passed':195,'skipped':0},'protected_old_data_files':len(protected),'changed_existing_files':changed,
            'new_hsd_bytes':plan['new_hsd_bytes'],'new_range_payload_bytes':range_new,'copied_old_range_bytes':range_total-range_new,
            'new_downloaded_satellite_payload_bytes':plan['new_hsd_bytes']+range_new,
            'total_current_archived_satellite_bytes':plan['new_hsd_bytes']+range_total,
            'budget_bytes':plan['maximum_archived_batch_bytes'],
            'default_changed':False,'final_material':'screened_candidate',
            'limits':'Metadata protection is not a full old-data content hash. Source crop expanded using actual observations; not global cloud coverage. '
                     '2km categorical boundaries and 3km city-light source limits remain. Cloud masks are fallible, not ground truth. '
                     'Cross-GPU historic comparisons are not code regression checks. Sea material/scattering/exposure unchanged in cloud tests.'}
    (root/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    page='<meta charset="utf-8"><title>Targeted cloud / lights / ocean fixes</title><style>body{background:#0b1019;color:#e1ebf5;font:16px system-ui;margin:24px}img{max-width:100%}a{color:#9ed9ff}</style>'
    page+='<h1>Hinnamnor targeted candidate: reversible, defaults retained</h1><p>Two observed scans: 2022-08-31 10:00 and 11:30 UTC. Separate source coverage, tint, clear screen, light resolution/gain and ocean diagnostics. No synthetic clouds, no whole-image blur, no weather interpolation.</p>'
    page+='<p><a href="../../../docs/HINNAMNOR_TARGETED_FIXES_V1.md">Chinese cause and QA report</a> | <a href="verification.json">Verification</a></p>'
    for stamp in ['1000','1130']:
        for name in ['before_after','colour_only_pair','clear_only_pair','atmosphere_pair','airglow_pair','city_lights_pair']:
            file=root/'render_screened'/(stamp+'_'+name+'.png')
            if file.exists():page+='<h2>'+stamp+' UTC / '+name+'</h2><img src="render_screened/'+file.name+'">'
    for name in ['lights_4k_pair','lights_gain_only_pair','lights_actual_clouds_pair','sea_no_clouds_pair','sea_no_atmosphere_pair','sea_no_reflections_pair','sea_deep_water_candidate_pair']:
        page+='<h2>'+name+'</h2><img src="lights_sea_same_gpu/'+name+'.png">'
    page+='<h2>Unresized city crops: source limit remains</h2>'
    for name in ['crop_4096_no_clouds','crop_13500_no_clouds','crop_13500_gain1']:
        page+='<img src="lights_sea_same_gpu/'+name+'.png">'
    page+='<h2>Old ROI crop / candidate, same pixel scale</h2><img src="details/internal_roi_crop.png">'
    page+='<h2>Integrated 4K illustration (multiple controlled changes combined)</h2><img src="details/combined_screened_4k.png">'
    (root/'index.html').write_text(page,encoding='utf-8')
    print('FINAL PASS',len(protected),'old files;same GPU40 exact;new payload',plan['new_hsd_bytes']+range_new,flush=True)


if __name__=='__main__':main()
