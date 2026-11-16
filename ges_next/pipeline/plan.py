"""Freeze a selected H9 project and real catalog objects before payload transfer."""
from datetime import datetime
import json
from pathlib import Path
import shutil
from ges.native_bridge import project_times
from ges_next.inventory_selection import selection
from ges_next.production.assets import digest,write_json
from ges_next.production.rebuild_recipe import validate


def runtime_signature(profile=None):
    root=Path(__file__).resolve().parents[2]
    files=['ges_next/production/h9_job.py','ges_next/production/h9_layers.py','ges_next/production/profile.py',
           'ges_next/production/night_detail.py','ges_next/production/night_reference.py','ges_next/production/static_night.py',
           'scripts/blender_support/production_layers.py','scripts/blender_support/layered_atmosphere.py',
           'ges/earth_validation/solar_shared.py','ges/earth_validation/solar_satpy_config/composites/ahi.yaml',
           'ges/earth_validation/bootstrap.py','ges_next/production/__main__.py']
    if (profile or {}).get('NightMode') in ('ai-vis','ai-vis-ir'):
        files+=['ges_next/production/neutral_night.py','ges_next/algorithms/night_modes.py','ges_next/algorithms/night_catalog.py','ges_next/production/night_layers.py',
            'ges_next/production/rebuild_recipe.py','ges_next/production/h9_source.py','ges_next/production/qualified_static.py','resources/references/qualified_h9_landmask_v1/eee9736ff7b78420e1cc09ca9c27e08508293b524767bdf7be86fe1353d19361.json','resources/references/qualified_h9_landmask_v1/manifest.json']
        files += [p.relative_to(root).as_posix() for p in sorted((root/'ges_next/algorithms/aivis').glob('*.py'))]
        files += ['resources/models/aivis/aivis_setup/author/pix2pix.py','resources/models/aivis/aivis_setup/author/himawari8.npz']
    files+=['ges_next/production/qualified_static.py', 'resources/references/qualified_h9_landmask_v1/manifest.json', 'resources/references/qualified_h9_landmask_v1/eee9736ff7b78420e1cc09ca9c27e08508293b524767bdf7be86fe1353d19361.json']
    # Large reference pixels are pinned in the manifest and verified by qualified_static.seed per real job.
    return {name:digest(root/name) for name in dict.fromkeys(files)}


def signature(project):
    result = {key:project.get(key) for key in ['Id','StartUtc','EndUtc','IntervalMinutes','SatelliteSelection','Production','Scope','Recipe','DataDirectory']}
    # Keep existing frozen sequence queues compatible; distinguish single-frame plans.
    if project.get('CaptureMode', 'sequence') == 'single': result['CaptureMode']='single'
    return result


def create(project,inventory,output,previous=None,reuse_source=None):
    from ges_next.isolation import require_writable
    mode,ids=selection(project)
    if project.get('Scope','global-nonpolar')!='global-nonpolar' or project.get('Recipe','geocolor-style')!='geocolor-style':
        raise ValueError('区域裁切或其他配方尚未接入此队列；不会忽略范围并制作完整圆盘')
    if mode!='manual' or ids!=['himawari9']:raise ValueError('当前流水线只接入H9单星；多星/全球项目不能被静默替换成H9')
    profile=project.get('Production',{})
    from ges_next.algorithms.night_modes import recipe as select_night
    selected_night=select_night(profile)
    optional_night=selected_night.mode!='geocolor'
    if optional_night:
        from ges_next.production.night_layers import preflight
        preflight(profile)
    if profile.get('Format')!='jpeg' or profile.get('HimawariDiskSize')!=11000 or profile.get('NightLightMetres') not in (500,1000):
        raise ValueError('当前流水线支持H9 11K JPG＋500m/1km独立夜景；其他档位待适配')
    if type(profile.get('JpegQuality')) is not int or not 1<=profile['JpegQuality']<=100:raise ValueError('JPEG质量必须是1..100整数')
    data=json.loads(Path(inventory).read_text(encoding='utf-8'))
    if data.get('project_id')!=str(project['Id']) or not data.get('finished'):raise ValueError('需要本项目已完成的目录预检')
    old=data.get('project_spec')
    if old and signature(old)!=signature(project):raise ValueError('项目参数在预检后变化，请重新检查')
    times=project_times(project);rows=data['records'];steps={};nodes=[]
    requested=[datetime.fromisoformat(row['requested_utc'].replace('Z','+00:00')) for row in rows]
    if len(rows)!=len(times) or sorted(requested)!=times:raise ValueError('目录时间或卫星数量与H9项目不一致')
    for when in times:
        row=next(r for r,t in zip(rows,requested) if t==when)
        if row.get('source')!='himawari9':raise ValueError('目录含未选择卫星；请重新预检')
        utc=when.strftime('%Y-%m-%dT%H:%M:%SZ');node=dict(utc=utc,state='missing')
        native=row.get('native',{})
        if row.get('state')=='available' and native.get('satellite')=='himawari9':
            actual=datetime.fromisoformat(native['observed_utc'].replace('Z','+00:00'))
            if actual==when:
                keys,sizes,etags=native['keys'],native['sizes'],native['etags']
                if len(keys)!=len(sizes) or len(keys)!=len(etags):raise ValueError('目录对象身份不完整')
                objects=[dict(bucket=native['bucket'],key=k,bytes=s,etag=e) for k,s,e in zip(keys,sizes,etags)]
                # Same strict identity/band/segment validation as rebuild; hashes are learned after download.
                validation=dict(schema='earthstudio.h9.rebuild.v1',utc=utc,inputs=[dict(item,sha256='0'*64) for item in objects])
                if optional_night:validation.update(profile={'NightMode':selected_night.mode},night_recipe=selected_night.identity())
                validate(validation)
                steps[utc]=dict(utc=utc,objects=objects);node['state']='catalog_available'
            else:node.update(state='nearby-scan-not-substituted',nearby_utc=native['observed_utc'])
        nodes.append(node)
    if not steps:raise ValueError('没有精确匹配的完整H9扫描，不能开始下载')
    inherited=None;references={}
    if previous and reuse_source:raise ValueError("追加与跨项目复用不能同时使用")
    if reuse_source:
        from .extension import reuse_completed
        inherited,references=reuse_completed(reuse_source,signature(project),list(steps.values()))
    if previous:
        from .extension import inherit
        inherited,references=inherit(previous,signature(project),list(steps.values()))
    root=require_writable(output)
    if root.exists() and any(root.iterdir()):raise FileExistsError('请为新队列选择空目录')
    root.mkdir(parents=True,exist_ok=True)
    largest=max(sum(obj['bytes'] for obj in s['objects']) for s in steps.values())
    estimated=len(steps)*(240 if profile['JpegQuality']>=98 else 160)*1024**2
    if profile['NightLightMetres']==500:estimated+=len(steps)*64*1024**2
    new_steps=[s for s in steps.values() if s['utc'] not in references]
    estimated=round(estimated*len(new_steps)/len(steps))
    minimum=largest+(18 if profile['NightLightMetres']==500 else 14)*1024**3
    if optional_night:minimum=max(minimum,largest+24*1024**3)
    result=dict(schema='earthstudio.h9.pipeline.v1',project=signature(project),inventory_sha256=digest(inventory),runtime=runtime_signature(profile),
        nodes=nodes,steps=list(steps.values()),missing_nodes=sum(n['state']!='catalog_available' for n in nodes),
        requested_nodes=len(nodes),download_bytes=sum(sum(o['bytes'] for o in s['objects']) for s in new_steps),
        largest_scan_bytes=largest,estimated_final_bytes=estimated,minimum_start_free_bytes=minimum,
        current_free_bytes=shutil.disk_usage(root).free,
        storage_note='正式素材是估算，非保证；逐时次校验余量，低于安全门槛暂停。旧缓存命中会减少实际下载。')
    if inherited:result.update(parent_revision=inherited,reused_packages=references,reused_scans=len(references),new_scans=len(new_steps))
    write_json(root/'plan.json',result)
    write_json(root/'state.json',dict(phase='planned',completed=list(references),first_sample=None,plan_sha256=digest(root/'plan.json')))
    return result
