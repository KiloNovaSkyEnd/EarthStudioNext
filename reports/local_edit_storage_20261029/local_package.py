"""Copy formal assets into a self-contained new delivery; never hardlink/delete sources."""
from datetime import datetime
import json
from pathlib import Path
import shutil
import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS=500_000_000
from ges_next.production.assets import record,write_json,digest,verify_assets
from ges_next.layered_sequence.collection import collect,ROLES


def build(packages,output,step_minutes=10,report=lambda value:None,storage="local"):
    if storage not in ("local","copy"):raise ValueError("Unknown storage policy")
    from ges_next.isolation import require_writable
    nodes,grid=collect(packages,step_minutes);out=require_writable(output)
    if any(out.is_relative_to(n['source']['package']) for n in nodes if n['source']):raise ValueError('交付目录不能位于只读源包内部')
    if out.exists() and any(out.iterdir()):raise FileExistsError('请选择新的交付目录，不覆盖旧结果')
    needed=(sum(sum(a["bytes"] for a in n["source"]["commit"]["assets"]) for n in nodes if n["source"]) if storage=="copy" else 0)+len(nodes)*16*1024**2+1024**3
    out.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(out).free<needed:raise ValueError('可用空间不足以复制独立交付素材')
    files=[];proxy_files=[];sources=[];public=[];suns=[];shape=grid['shape']
    night_hashes={next(a['sha256'] for a in n['source']['commit']['assets'] if a['role']==ROLES['night'][0]) for n in nodes if n['source']}
    static=['night'] if len(night_hashes)==1 else []
    first_source=next(n['source'] for n in nodes if n['source'])
    from ges.solar import sun_direction
    for node in nodes:
        index=node['index'];source=node['source']
        for name,(role,extension) in ROLES.items():
            if name in static and index>1:continue
            layer_source=first_source if name in static else source
            from ges_next.production.night_detail import layer_shape
            role_shape=layer_shape(grid,role)
            path=out/f'assets/{name}/weather_{index:04d}{extension}';path.parent.mkdir(parents=True,exist_ok=True)
            if layer_source:
                item=next(a for a in layer_source['commit']['assets'] if a['role']==role)
                if storage=="local":
                    import os
                    try:os.link(layer_source['package']/item['path'],path)
                    except OSError as exc:raise ValueError("Local editing requires same-volume hard links; no automatic full copy. Select a same-drive output or explicitly choose independent copy.") from exc
                else:shutil.copyfile(layer_source['package']/item['path'],path)
                if digest(path)!=item['sha256']:raise ValueError('复制后素材校验失败')
            else:
                mode='RGB' if extension=='.jpg' else 'I;16' if name=='transmission' else 'L'
                Image.new(mode,(role_shape[1],role_shape[0])).save(path,quality=95,subsampling=0)  # Explicit blank support, no borrowed observation.
            files.append(dict(record(out,path,role,role_shape),static=name in static))
            proxy=out/f'preview_layers/{name}/weather_{index:04d}{extension}';proxy.parent.mkdir(parents=True,exist_ok=True)
            with Image.open(path) as image:
                small=image.resize((min(1024,shape[1]),min(1024,shape[0])),Image.Resampling.NEAREST)
                small.save(proxy,quality=90,subsampling=0)
            proxy_files.append(dict(record(out,proxy,role,[small.height,small.width]),static=name in static))
        if source:
            meta=out/f'provenance/{index:04d}';meta.mkdir(parents=True)
            for filename in ('commit.json','rebuild_recipe.json'):
                shutil.copyfile(source['package']/filename,meta/filename)
                files.append(record(out,meta/filename,'source-provenance'))
            sources.append(dict(index=index,utc=node['utc'],commit_sha256=source['commit_sha256']))
        public.append({k:node[k] for k in ('index','utc','missing')})
        suns.append(sun_direction(datetime.fromisoformat(node['utc'].replace('Z','+00:00'))).tolist())
        report(dict(phase='linking-layered-sequence' if storage=='local' else 'copying-layered-sequence',completed=index,total=len(nodes)))
    first_layers=[a for a in files if a['path'].startswith('assets/')][:4]
    master=dict(shape=shape,extent=grid['extent'],crs=grid['crs'],production_layers=first_layers,
        production_sequence=dict(count=len(nodes),clock_start=0,clock_end=(len(nodes)-1)*step_minutes/60),
        preview_layers=proxy_files[:4])
    manifest=dict(storage_policy=storage,shared_immutable_assets=(storage=="local"),schema='earthstudio.layered_weather_sequence.v1',nodes=public,suns=suns,files=files,sources=sources,
        native_shape=shape,step_minutes=step_minutes,raw_L1_required=False,weather_interpolation=False,static_components=static,
        missing_policy='Blank support; no substituted native scan',encoding='Primary JPEG RGB; lossless scalar PNG',
        visual_acceptance_pending=True)
    manifest['auxiliary_files']=proxy_files
    night_recipe=first_source['commit'].get('night_recipe',{}).get('recipe')
    if night_recipe:manifest['night_recipe']=night_recipe
    verify_assets(out,files+proxy_files);write_json(out/'native_master.json',master)
    manifest['auxiliary_files'].append(record(out,out/'native_master.json','grid-and-layer-layout'))
    write_json(out/'sequence_manifest.json',manifest)
    return manifest
