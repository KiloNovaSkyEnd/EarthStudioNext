from __future__ import annotations
import argparse
import json
from pathlib import Path
from .catalog import utc_time, s3_client, himawari_scene, goes_scene, scene_as_json
from .download import download_scene, cached_bytes
from .storage import load_config, preflight
from .render import render, combine_images


def main():
    parser = argparse.ArgumentParser(prog='ges',description='真实 NOAA 气象卫星影像 → 全球经纬度云图 → Blender 静态地球')
    commands = parser.add_subparsers(dest='cmd',required=True)
    for cmd in ('search','download'):
        p = commands.add_parser(cmd)
        p.add_argument('--utc',required=True,help='2020-10-29T16:40:00Z')
        p.add_argument('--satellite',default='auto',choices=['auto','himawari8','himawari9','goes16','goes17','goes18','goes19'])
        p.add_argument('--product',default='ir-bd',choices=['rgb','ir-bd','ir-gray'])
        p.add_argument('--minutes',type=int,default=20,choices=[10,20,30,40,50,60])
        if cmd=='download':
            p.add_argument('--out',default=None, help='可选覆盖原始数据目录（否则使用 local_storage.json）')
    p = commands.add_parser('render')
    p.add_argument('--manifest',required=True)
    p.add_argument('--product',default='ir-bd',choices=['rgb','ir-bd','ir-gray'])
    p.add_argument('--width',type=int,default=2048)
    p.add_argument('--out',default=None, help='可选覆盖已处理数据目录')
    p = commands.add_parser('mosaic')
    p.add_argument('--images',nargs='+',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--utc', default=None, help='叠加参考 UTC；默认第一个输入的观测时间')
    p = commands.add_parser('solar', help='输出计算的太阳权重（不是卫星云图）')
    p.add_argument('--utc', required=True)
    p.add_argument('--width', type=int, default=2048)
    p.add_argument('--out', default=None, help='权重和诊断图输出目录')
    p=commands.add_parser('storage',help='显示本地数据路径和预算，不下载任何文件')
    p=commands.add_parser('night',help='由冷白红外及独立静态夜光制作夜间显示近似')
    p.add_argument('--image',required=True)
    p.add_argument('--lights',required=True)
    p.add_argument('--out',default=None)
    p=commands.add_parser('meteosat-search',help='查询真实历史 SEVIRI 目录；不下载、不生成云图')
    p.add_argument('--utc',required=True)
    p.add_argument('--service',choices=['zero','iodc','both'],default='both')
    p.add_argument('--minutes',type=int,default=20)
    p.add_argument('--out',default=None,help='可选保存候选目录 JSON')
    p=commands.add_parser('night-multispectral',help='真实双波段夜间增强：蓝色液态云候选/灰白冷红外；非云型分类')
    p.add_argument('--manifests',nargs='+',required=True)
    p.add_argument('--base',default=None,help='可选匹配的既有双波段结果；保留原始源索引并新增真实覆盖')
    p.add_argument('--lights',required=True)
    p.add_argument('--width',type=int,default=2048)
    p.add_argument('--out',required=True)
    p=commands.add_parser('meteosat-download',help='下载目录候选中的真实 SEVIRI 原始数据；使用本机加密凭据')
    p.add_argument('--inventory',required=True)
    p=commands.add_parser('blend-ir',help='按观测角度/覆盖边缘混合真实重叠红外；仅显示产品，不是标定亮温融合')
    p.add_argument('--sources',required=True,help='含真实投影几何和原始处理图路径的 JSON 列表')
    p.add_argument('--out',required=True)
    p.add_argument('--utc',required=True)
    p.add_argument('--feather',type=int,default=64)
    p=commands.add_parser('cloud-evidence',help='真实云掩膜、云相/气压或云顶高度约束夜间低云；AHI、ABI、SEVIRI 分开保留不确定性')
    p.add_argument('--ir-manifest',required=True)
    p.add_argument('--l2-manifest',required=True)
    p.add_argument('--lights',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--width',type=int,default=8192)
    p=commands.add_parser('daylight',help='真实 ABI 可见光近真彩色；声明合成绿色分量，不是云掩膜')
    p.add_argument('--manifest',required=True);p.add_argument('--out',required=True)
    p.add_argument('--width',type=int,default=8192)
    p=commands.add_parser('day-night',help='合成真实日侧 RGB 与已验证的过渡红外/夜间显示；保留缺测权重')
    p.add_argument('--day',required=True);p.add_argument('--night',required=True)
    p.add_argument('--out',required=True);p.add_argument('--utc',required=True)
    args=parser.parse_args()
    cfg=load_config()
    if args.cmd=='storage':
        print(json.dumps({'raw_dir':str(cfg.raw_dir),'processed_dir':str(cfg.processed_dir),
             'export_dir':str(cfg.export_dir),'max_single_scene_gb':cfg.max_single_scene_gb,
             'reserve_free_gb':cfg.reserve_free_gb},ensure_ascii=False,indent=2))
        return
    if args.cmd in ('search','download'):
        t=utc_time(args.utc)
        sat=args.satellite
        if sat=='auto':
            from .catalog import selected_himawari
            sat=selected_himawari(t)
        s3=s3_client()
        if sat.startswith('himawari'):
            # true color needs 3 AHI reflective bands; IR products use 10.4um B13.
            bands = ('B01','B02','B03') if args.product=='rgb' else ('B13',)
            scene=himawari_scene(s3,t,bands,args.minutes)
        else:
            scene=goes_scene(s3,t,sat,args.minutes)
        meta=scene_as_json(scene)
        meta['note']='Search only queries actual AWS objects. Historical products may be absent.'
        print(json.dumps(meta,indent=2,ensure_ascii=False))
        if args.cmd=='download':
            print('Downloading actual satellite files. This may use gigabytes of disk and bandwidth.')
            raw_root=Path(args.out) if args.out else cfg.raw_dir
            print('PRE-FLIGHT:', preflight(scene.total_bytes,raw_root/scene.scene_id,cfg,
                  existing_bytes=cached_bytes(scene,raw_root/scene.scene_id)))
            path=download_scene(s3,scene,raw_root,cfg)
            print('MANIFEST:',path)
    elif args.cmd=='render':
        out=render(Path(args.manifest),Path(args.out) if args.out else cfg.processed_dir,args.product,args.width)
        print('PROCESSED:',out)
    elif args.cmd=='mosaic':
        print('MOSAIC:', combine_images([Path(p) for p in args.images],Path(args.out),
              utc_time(args.utc) if args.utc else None))
    elif args.cmd=='solar':
        from .solar import export_solar_weights
        print('SOLAR MODEL:', export_solar_weights(utc_time(args.utc),
              Path(args.out) if args.out else cfg.processed_dir / 'solar', args.width))
    elif args.cmd=='night':
        from .night import prepare_night_display
        print('NIGHT DISPLAY (approximation):', prepare_night_display(Path(args.image),
              Path(args.lights),Path(args.out) if args.out else cfg.processed_dir / 'night'))
    elif args.cmd=='meteosat-search':
        from .meteosat import search_observation
        services=['zero','iodc'] if args.service=='both' else [args.service]
        result={'kind':'SEVIRI candidate inventory, no added cloud pixels',
                'candidates':[search_observation(utc_time(args.utc),service,args.minutes) for service in services]}
        body=json.dumps(result,indent=2,ensure_ascii=False)
        if args.out:
            target=Path(args.out)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(body,encoding='utf-8')
        print(body)
    elif args.cmd=='night-multispectral':
        from .multispectral import render_multispectral
        print('EXPERIMENTAL MULTISPECTRAL:',render_multispectral(args.manifests,args.lights,args.out,args.width,args.base))
    elif args.cmd=='meteosat-download':
        from .meteosat_download import download_candidates
        inventory=json.loads(Path(args.inventory).read_text(encoding='utf-8'))
        download_candidates(inventory['candidates'])
    elif args.cmd=='blend-ir':
        from .blend import blend_ir
        records=json.loads(Path(args.sources).read_text(encoding='utf-8'))
        print('DERIVED DISPLAY BLEND:',blend_ir(records,args.out,args.utc,args.feather))
    elif args.cmd=='cloud-evidence':
        from .cloud_evidence import render_cloud_evidence
        print('L2-SUPPORTED NIGHT DISPLAY:',render_cloud_evidence(args.ir_manifest,args.l2_manifest,args.lights,args.out,args.width))
    elif args.cmd=='daylight':
        from .daylight import render_daylight
        print('OBSERVED DAYLIGHT RGB:',render_daylight(args.manifest,args.out,args.width))
    elif args.cmd=='day-night':
        from .day_night import compose_day_night
        print('OBSERVED DAY/NIGHT DISPLAY:',compose_day_night(args.day,args.night,args.out,args.utc))

if __name__=='__main__':
    main()
