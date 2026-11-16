"""Validate frozen experiment, assemble A/B/C review pages and report factual metrics."""
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from ges.storage import load_config
from scripts.compare_hinnamnor_geocolor import sha


def main():
    cfg=load_config();root=cfg.processed_dir/'hinnamnor_geocolor_v1'
    rows=[];checks=[]
    for stamp in ['0830','1000','1130']:
        folder=root/stamp
        m=json.loads((folder/'comparison_metrics.json').read_text())
        with np.load(folder/'official_layers.npz') as f:a={k:f[k] for k in f.files}
        with np.load(folder/'observed_inputs.npz') as f:raw={k:f[k] for k in f.files}
        with np.load(folder/'comparison_layers.npz') as f:b={k:f[k] for k in f.files}
        expand=lambda x:np.repeat(np.repeat(x,2,0),2,1)
        lat=expand(raw['latitude_2km']);temp=expand(raw['B13'])
        tmin=210+20*np.clip((abs(lat)-30)/30,0,1)
        expected_high=np.clip((300-temp)/(300-tmin),0,1)
        expected_low=np.where(temp>=230,np.clip(expand(raw['B13']-raw['B07'])/4,0,1),0)
        high_error=float(np.nanmax(abs(expected_high-b['A_high_alpha'])))
        low_error=float(np.nanmax(abs(expected_low-b['A_low_alpha'])))
        assert high_error<1e-4 and low_error<1e-4,(stamp,high_error,low_error)
        assert b['A_high_alpha'].shape==b['B_alpha'].shape==(2300,3000)
        assert np.isfinite(a['official_geo_rgb']).all(), 'Official output has nonfinite pixels'
        # Check nested composition independently, against the actual official PNG.
        alpha=b['A_cloud_alpha']
        premult=(a['high_grey']*b['A_high_alpha'])[...,None]+((1-b['A_high_alpha'])*b['A_low_alpha'])[...,None]*np.array([.55,.75,.98])
        reconstructed=premult+a['official_night_background']*(1-alpha[...,None])
        actual=np.asarray(Image.open(folder/'A_geo_color_night.png').convert('RGB'),float)/255
        stack_error=float(np.nanmax(abs(np.clip(reconstructed,0,1)-actual)))
        assert stack_error<=1.01/255,(stamp,stack_error)
        night=a.get('official_night_rgb',actual)
        w=b['A_day_weight'][...,None]
        # enhance2dataset clips branches; zero_missing_data handles missing day
        # radiance in the fully nocturnal scene before multiplying by zero.
        day_rgb=np.nan_to_num(np.clip(a['official_day_rgb'],0,1))
        night_rgb=np.nan_to_num(np.clip(night,0,1))
        blend_error=float(np.nanmax(abs(a['official_geo_rgb']-(day_rgb*w+night_rgb*(1-w)))))
        assert blend_error<=1.01/255,(stamp,'official solar blend',blend_error)
        checks.append({'utc':m['nominal_utc'],'high_alpha_formula_max_error':high_error,
                       'low_alpha_formula_max_error':low_error,'night_stack_max_error_dn':stack_error*255,
                       'solar_blend_max_error_dn':blend_error*255,
                       'official_rgb_finite':True,'same_grid':True})
        m['A_blue_proxy_percent']=m['A_blue_proxy_pixels']/6900000*100
        m['B_blue_proxy_percent']=m['B_blue_proxy_pixels']/6900000*100
        m['B_paired_spectral_blue_proxy_percent']=m['B_paired_spectral_blue_proxy_pixels']/6900000*100
        rows.append(m)
        def panel(files,names,name,alpha_preview=False):
            sheet=Image.new('RGB',(900*len(files),726),'#0b1019');draw=ImageDraw.Draw(sheet)
            for i,(file,label) in enumerate(zip(files,names)):
                im=Image.open(folder/file).convert('RGBA')
                if alpha_preview:
                    bg=Image.new('RGBA',im.size,(18,23,32,255));bg.alpha_composite(im);im=bg
                im=im.convert('RGB').resize((900,690),Image.Resampling.LANCZOS)
                sheet.paste(im,(i*900,36));draw.text((i*900+12,10),stamp+' UTC | '+label,fill='white')
            sheet.save(folder/name)
        panel(['A_geo_color.png','B_current_flat_preview.png'],
              ['A official GeoColor full scene','B current cloud material, flat on static night background'],
              'AB_full_and_material.png')
        panel(['A_official_cloud_stack_rgba.png','B_current_upload_rgba.png'],
              ['A night cloud stack diagnostic','B current uploaded cloud alpha, no 3D volume'],
              'AB_clouds_common_background.png',True)
        panel(['A_day_weight.png','B_day_weight.png','C_low_blue_support.png'],
              ['A day selection (white=day)','B day selection (white=day)','Blue support: red A only / blue B only / green both'],
              'C_transition_and_support.png')
    downloads=json.loads((root/'download_verification.json').read_text())
    protected=json.loads((root/'protected_before.json').read_text())
    assert all(Path(p).exists() and [Path(p).stat().st_size,Path(p).stat().st_mtime_ns]==v for p,v in protected.items())
    old=json.loads((cfg.processed_dir/'audit_baseline_20261019/render_b/verification.json').read_text())
    assert all(sha(p)==v for p,v in old['input_sha256'].items()), 'Earlier baseline input changed'
    source=json.loads((root/'source_snapshot/verification.json').read_text())
    assert all(sha(v['installed_path'])==v['sha256'] for v in source['sources'].values())
    range_bytes=sum(p.stat().st_size for p in (cfg.raw_dir/'hinnamnor_geocolor_l2_ranges').rglob('*.bin'))
    retained=sum(p.stat().st_size for p in (cfg.raw_dir/'hinnamnor_geocolor_v1').rglob('*') if p.is_file() and p.name!='manifest.json')
    refs=sum(r['bytes'] for r in downloads['references'])
    total=range_bytes+retained+refs
    assert total<5_000_000_000
    packages={name:importlib.metadata.version(name) for name in ['satpy','numpy','dask','xarray','trollimage','pyspectral','pyresample','rasterio','rioxarray']}
    result={'samples':rows,'independent_formula_checks':checks,'packages':packages,
            'original_baseline_all_106_inputs_unchanged':True,'installed_satpy_sources_configs_unchanged':True,
            'original_raw_exports_size_mtime_unchanged':True,'protected_files':len(protected),
            'retained_hsd_whole_l2_and_partial_bytes':retained,'l2_range_bytes':range_bytes,
            'static_reference_and_paper_bytes':refs,'actual_archived_payload_bytes':total,
            'payload_budget_bytes':5_000_000_000,
            'limits':'Stored payload bytes include retained interrupted L2 .part files; not a measurement of wire traffic. '
                      'Raw range blocks are not full NetCDF. Three independent acquisitions, no dense temporal validation. '
                      'A is full GeoColor; B is an isolated replay of existing native v6 cloud material, not a 3D render. '
                      'Official A self-sharpening and nearest-grid workflow vs B conservative 500m->1km averaging confound attribution of fine texture. '
                      'Blue-support metrics are algorithmic display proxies, not truth or equivalent cloud classifications.'}
    (root/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    cols=['nominal_utc','A_blue_proxy_percent','B_blue_proxy_percent','B_paired_spectral_blue_proxy_percent','A_cloud_alpha_mean','B_material_alpha_mean',
          'B_uploaded_alpha_mean','A_day_weight_mean','B_day_weight_mean','navigation_max_error_deg']
    with (root/'metrics.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader();writer.writerows({k:r[k] for k in cols} for r in rows)
    page='''<!doctype html><meta charset="utf-8"><title>Hinnamnor GeoColor A/B/C</title>
<style>body{background:#0b1019;color:#dfeaf7;font:16px system-ui;margin:26px}img{max-width:100%}a{color:#9ed9ff}p{max-width:1000px}</style>
<h1>Satpy 0.60.0 / Hinnamnor A-B-C</h1>
<p>2022-08-31 08:30 / 10:00 / 11:30 UTC. Same AHI geos rectangle and 3000x2300 1km grid. IR information remains2km.</p>
<p>A: installed official GeoColor. B: current native v6 cloud material and alpha, flat diagnostic only. A includes ground and daytime observed colour; B shown over a static night reference is NOT the project's complete 3D Earth. Use cloud-only and alpha controls below to avoid confusing background differences with cloud quality. GeoColor is a benchmark, not meteorological ground truth.</p>
<p><a href="../../../docs/HINNAMNOR_GEOCOLOR_COMPARISON.md">Chinese technical report</a> | <a href="verification.json">Verification/provenance</a> | <a href="metrics.csv">Metrics</a></p>'''
    for stamp in ['0830','1000','1130']:
        page+='<h2>'+stamp+' UTC</h2>'
        for name in ['AB_full_and_material.png','AB_clouds_common_background.png','C_transition_and_support.png']:
            page+='<img src="'+stamp+'/'+name+'">'
        page+='<p>'+' | '.join('<a href="'+stamp+'/'+name+'">'+label+'</a>' for label,name in
            [('A full','A_geo_color.png'),('B raw RGBA','B_current_material_rgba.png'),('A high alpha','A_high_alpha.png'),
             ('A low alpha','A_low_alpha.png'),('B alpha','B_alpha.png'),('Alpha difference (red B greater, blue A greater)','C_alpha_difference.png'),
             ('L2 schema','l2_schema.json'),('Matched grid/UTC','official_metadata.json')])+'</p>'
    (root/'index.html').write_text(page,encoding='utf-8')
    print('FINAL VALIDATION',json.dumps({'checks':checks,'metrics':[{k:r[k] for k in cols} for r in rows],'payload_bytes':total},indent=2),flush=True)


if __name__=='__main__':main()
