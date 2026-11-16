"""Reframe cached cloud layers and isolate a small 0.35 -> 0.40 height change.

No source resampling, sharpening, new imagery or measurement changes.
Run: python -m scripts.review_cloud_relief
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import numpy as np
from PIL import Image, ImageDraw
from ges.atmosphere_scattering import ScatteringRenderer, geographic, orbit_camera
from ges.catalog import utc_time
from ges.solar import sun_direction
from ges.storage import load_config


def review_camera(longitude, altitude=2500, target_fraction=.35):
    """Diagnostic framing only; keep the older grazing camera unchanged."""
    tangent = math.degrees(math.acos(6371/(6371+altitude)))
    position = geographic(longitude,15,6371+altitude)
    target = geographic(longitude+tangent*target_fraction,15,6371)
    return dict(position=position,target=target,up=position/np.linalg.norm(position),fov=45)


def angles(camera):
    p=np.asarray(camera['position']);t=np.asarray(camera['target'])
    ray=(t-p)/np.linalg.norm(t-p)
    return {'camera_off_nadir_deg':float(np.rad2deg(np.arccos(np.clip(np.dot(ray,-p/np.linalg.norm(p)),-1,1)))),
            'target_view_zenith_deg':float(np.rad2deg(np.arccos(np.clip(np.dot(-ray,t/np.linalg.norm(t)),-1,1))))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--width',type=int,default=1280)
    args=parser.parse_args()
    processed=load_config().processed_dir; source=processed/'cloud_relief_v1';out=processed/'cloud_relief_v2'
    report=json.loads((source/'verification.json').read_text());out.mkdir(parents=True,exist_ok=True)
    records=[];framing_rows=[];strength_rows=[]
    for sample in report['samples']:
        name=sample['sample'];folder=source/name;dest=out/name;dest.mkdir(exist_ok=True)
        inputs=[folder/'independent_cloud.png',folder/'static_ground.png',folder/'retrieved_height.npz',folder/'height_support.png',folder/'observation_coverage.png']
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
        cloud=np.asarray(Image.open(inputs[0]).convert('RGBA'));ground=np.asarray(Image.open(inputs[1]).convert('RGB'))
        with np.load(inputs[2]) as f:height=f['height_km'].copy()
        renderer=ScatteringRenderer([ground]*3,args.width,args.width*9//16,supersample=1.5,cloud_layer=(cloud,height))
        longitude=-130 if name.startswith('goes17') else -85
        cases=[('old_grazing600_035',orbit_camera(longitude,15,600,heading=1),.35,600),
               ('moderate2500_035',review_camera(longitude),.35,2500),
               ('moderate2500_040',review_camera(longitude),.40,2500),
               ('moderate3500_040',review_camera(longitude,3500),.40,3500)]
        images={};views=[]
        sun=sun_direction(utc_time(sample['source_utc']))
        for label,camera,strength,altitude in cases:
            pixels=renderer.render(camera,sun,steps=48,sun_steps=12,relief_strength=strength)
            Image.fromarray(pixels).save(dest/(label+'.png'));images[label]=pixels
            views.append({'file':label+'.png','height_strength':strength,'altitude_km':altitude,
                          'camera':{k:np.asarray(v).tolist() for k,v in camera.items()},**angles(camera)})
        renderer.close()
        def panel(first,second,label):
            im=Image.new('RGB',(args.width*2,args.width*9//16+36),(10,14,22))
            for i,key in enumerate([first,second]):im.paste(Image.fromarray(images[key]),(i*args.width,36))
            ImageDraw.Draw(im).text((12,10),name+' | '+sample['source_utc']+' | '+label,fill='white')
            return im
        framing=panel('old_grazing600_035','moderate2500_035','SAME height 0.35 | LEFT 600 km grazing / RIGHT 2500 km moderate')
        relief=panel('moderate2500_035','moderate2500_040','SAME 2500 km camera | LEFT height 0.35 / RIGHT height 0.40')
        framing.save(dest/'framing_comparison.png');relief.save(dest/'strength_comparison.png')
        framing_rows.append(framing);strength_rows.append(relief)
        for p in inputs:assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[p.name]
        delta=abs(images['moderate2500_035'].astype(np.int16)-images['moderate2500_040'].astype(np.int16))
        records.append({'sample':name,'source_layer_directory':str(folder.resolve()),'source_hashes_unchanged':hashes,
                        'views':views,'strength_only_mean_delta_dn':float(delta.mean()),
                        'strength_only_p99_delta_dn':float(np.quantile(delta,.99))})
        print('DONE',name,'camera angles',views[0]['target_view_zenith_deg'],views[1]['target_view_zenith_deg'],flush=True)
    for filename,rows in [('framing_comparison.png',framing_rows),('strength_comparison.png',strength_rows)]:
        sheet=Image.new('RGB',(rows[0].width,sum(row.height for row in rows)));y=0
        for row in rows:sheet.paste(row,(0,y));y+=row.height
        sheet.save(out/filename)
    metadata={'revision':'cloud-relief-camera-and-small-strength-review-v2','primary_altitude_km':2500,
              'secondary_altitude_km':3500,'primary_target_horizon_fraction':.35,'height_strength':.40,
              'comparison_controls':'same source grids, resolution, FOV, atmosphere, normal cue and UTC; camera change shown separately from strength change',
              'source_texture_dimensions':list(cloud.shape[1::-1]),'view_dimensions':[args.width,args.width*9//16],
              'source_report':str((source/'verification.json').resolve()),'samples':records,
              'limits':'Reframing does not restore native detail or reconstruct cloud thickness. Coarse height retrieval, achromatic daytime VIS, no parallax correction and incomplete weather playback/Blender remain v1 limitations. No extra sharpening, downloading, coverage change or noise.'}
    (out/'verification.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (out/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>云层机位与轻微起伏调整</title>
<style>body{margin:24px;background:#0b1019;color:#dbe7f5;font:16px system-ui}img{width:100%}a{color:#9cd8ff}</style>
<h1>先调整机位，再小幅增加起伏</h1>
<p>第一组：相同35%高度，左侧原600公里掠视，右侧2500公里中等斜视。镜头方向也向地表转回，避免仅拉远后仍然贴着地平线看。</p>
<img src="framing_comparison.png"><p>第二组：相同2500公里机位，左侧35%，右侧40%。纹理、云色和局部明暗参数保持相同。</p>
<img src="strength_comparison.png"><p>提高机位和俯角可减轻透视压缩与采样模糊，不会恢复原始缺失的细节。日侧仍为灰白VIS研究样本，尚无云底厚度；不代替连续气象延时验收。</p>
<p><a href="verification.json">来源校验、实际机位角度和参数</a></p>''',encoding='utf-8')
    print('REPORT',out/'index.html',flush=True)


if __name__=='__main__':main()
