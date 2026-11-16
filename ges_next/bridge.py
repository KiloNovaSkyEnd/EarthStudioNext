"""Next UI bridge, isolated writes and native-L1 date-aware NOAA inventory."""
from .inventory_selection import REGIONS,groups as project_groups,query as selected_query,selection
from .isolation import require_writable

def groups(when):
    return project_groups({'SatelliteSelection':{'Mode':'auto','Preset':'global','Satellites':[]}},when)


def main():
    import io
    import json
    import sys
    from pathlib import Path
    from .catalog_cache import CatalogCache
    from ges import native_bridge as legacy
    request=json.load(sys.stdin)
    user=Path(__import__('os').environ.get('LOCALAPPDATA',str(Path(__file__).resolve().parents[1]/'data')))/'Deepsky/EarthStudioNext'
    if request['action'] in ('configure-night','night-status'):
        from .night_resources import configure,resolve
        try:
            if request['action']=='configure-night':configure(request['options']['path'])
            path=resolve(check_pixels=True)
            import xml.etree.ElementTree as ET
            metres=500 if ET.parse(path).getroot().get('rasterXSize')=='86400' else 1000
            legacy.emit('result',night_valid=True,night_path=str(path),night_resolution_metres=metres,
                message=f'共享夜景参考可用：{metres}m全球地面灯光，VRT依赖及像素读取通过。'+str(path))
        except (ValueError,OSError,KeyError) as error:legacy.emit('result',night_valid=False,message=str(error))
        return
    if request['action']=='import-catalog':
        cache=CatalogCache(user/'catalog_cache')
        try:
            source=Path(request['options']['source']).resolve()
            if not source.exists():raise ValueError('所选检查记录位置不存在')
            before=cache.db.execute('SELECT count(*) FROM evidence').fetchone()[0]
            cache.import_inventories(source)
            after=cache.db.execute('SELECT count(*) FROM evidence').fetchone()[0]
            file=user/'catalog_sources.json';sources=json.loads(file.read_text(encoding='utf-8')) if file.exists() else []
            if str(source) not in sources:sources.append(str(source))
            file.write_text(json.dumps(sources,ensure_ascii=False),encoding='utf-8')
            legacy.emit('result',message=f'已导入外部目录记录，新增 {after-before} 项缓存；按当前日期继续检查即可复用。未下载卫星素材。')
        except (ValueError,OSError,KeyError) as error:
            legacy.emit('error',message='导入失败：'+str(error))
        finally:cache.close()
        return
    sys.stdin=io.StringIO(json.dumps(request))
    original_scan=legacy.scan
    original_query=legacy.query
    def query(when,choices,client):
        return selected_query(when,choices,client,original_query)
    def scan(project,out,**kwargs):
        require_writable(out)
        selection(project)
        data=Path(project.get('DataDirectory',Path(out).parent/(Path(out).name+'_local')))
        cache_path=user/'catalog_cache' if project.get('DataDirectory') else data/'catalog_cache'
        require_writable(cache_path)
        cache=CatalogCache(cache_path)
        from .algorithms.night_modes import recipe,signature as night_signature
        optional_night=recipe(project.get('Production',{})).mode!='geocolor'
        if optional_night:cache.version+=':night:'+night_signature(project['Production'])
        try:
            if not optional_night:cache.import_inventories(data/'projects')
            for config in ('storage_locations.json','catalog_sources.json'):
                file=user/config
                if file.exists() and not optional_night:
                    for source in json.loads(file.read_text(encoding='utf-8')):cache.import_inventories(source)
            refresh=request.get('options',{}).get('refresh',False)
            def cached(when,choices,client):
                if optional_night:
                    from .algorithms.night_catalog import probe_for
                    query_fn=lambda t,c,api:selected_query(t,c,api,original_query,probe_fn=probe_for(project['Production']))
                else:query_fn=query
                return cache.query(when,choices,client,query_fn,refresh=refresh)
            from .production.atomic_json import write_json
            result=original_scan(project,out,query_fn=cached,groups_fn=lambda when:project_groups(project,when),checkpoint_every=25,publish_fn=write_json,**kwargs)
            legacy.emit('status',message=f'目录检查完成：复用 {cache.hits} 项，新查 {cache.queries} 项；记录已保存。')
            return result
        finally:
            cache.close()
    legacy.candidates=groups
    legacy.scan=scan
    legacy.main()


if __name__=='__main__':main()
