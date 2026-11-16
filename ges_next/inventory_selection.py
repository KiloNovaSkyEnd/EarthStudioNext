"""Project search scope: explicit satellites are independent requests, never fallbacks."""
from .selection import candidates,select
from .noaa import probe

REGIONS=[('亚太 / AHI','asia_pacific'),('美洲 / GOES-East','americas_east'),
         ('太平洋 / GOES-West','americas_west'),('欧洲非洲 / Meteosat','europe_africa'),('印度洋 / IODC','indian_ocean')]
SATELLITES={
    'himawari8':('向日葵8号','asia_pacific'),'himawari9':('向日葵9号','asia_pacific'),
    'goes16':('GOES-16','americas_east'),'goes19':('GOES-19','americas_east'),
    'goes17':('GOES-17','americas_west'),'goes18':('GOES-18','americas_west'),
    'meteosat12':('Meteosat-12','europe_africa'),
    'meteosat_zero':('Meteosat历史欧洲非洲槽位','europe_africa'),
    'meteosat_iodc':('Meteosat印度洋槽位','indian_ocean')}


def selection(project):
    config=project.get('SatelliteSelection')
    if not isinstance(config,dict) or config.get('Mode') not in ('auto','manual'):
        raise ValueError('请选择自动推荐或手动选择卫星。')
    ids=config.get('Satellites',[])
    if not isinstance(ids,list) or any(not isinstance(s,str) or s not in SATELLITES for s in ids) or len(set(ids))!=len(ids):
        raise ValueError('卫星选择包含未知或重复项目。')
    if config['Mode']=='manual' and not ids: raise ValueError('搜索前请至少选择一颗卫星。')
    if config['Mode']=='auto' and config.get('Preset')!='global':
        raise ValueError('请先明确选择单星、自选多星或全球预设；不会默认查询全球。')
    return config['Mode'],ids


def groups(project,when):
    mode,ids=selection(project)
    if mode=='auto': return [(label,[c.satellite for c in candidates(when,region)]) for label,region in REGIONS]
    return [(SATELLITES[s][0],[s]) for s in ids]


def query(when,choices,client,historical_query,probe_fn=None):
    region=SATELLITES[choices[0]][1]
    available=[c for c in candidates(when,region) if c.satellite in choices]
    if not available:
        return dict(source='/'.join(choices),state='not-applicable',quality='所选卫星不在此日期的已支持候选范围；未查询或替换其他卫星')
    if region in ('europe_africa','indian_ocean'):
        if 'meteosat12' in choices:
            return dict(source='meteosat12',state='unavailable',quality='FCI真实归档适配待完成；未换用未选的旧卫星')
        result=historical_query(when,['zero' if region=='europe_africa' else 'iodc'],client)
        result['quality']='历史SEVIRI槽位目录；实际平台、大小、波段和覆盖需核验'
        return result
    result=select(when,region,lambda candidate,t:(probe_fn or probe)(client,candidate,t),allowed_satellites=choices)
    if result['selected'] is None:
        return dict(source='/'.join(choices),state='unavailable' if any(a['state']=='unavailable' for a in result['attempts']) else 'missing',selection=result)
    evidence=result['selected']['evidence']
    return dict(source=evidence['satellite'],observed=evidence['observed_utc'],bytes=evidence['total_bytes'],
        native=evidence,selection=result,quality='所选卫星L1目录完整；未下载，像元质量与覆盖未验证')
