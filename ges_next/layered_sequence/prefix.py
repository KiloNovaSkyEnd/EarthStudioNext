"""An edited Blender may only receive a verified extension of its existing observations."""
import json
from pathlib import Path

def verify_prefix(old_root,new_root):
    old_root,new_root=Path(old_root),Path(new_root)
    old=json.loads((old_root/'sequence_manifest.json').read_text(encoding='utf-8'))
    new=json.loads((new_root/'sequence_manifest.json').read_text(encoding='utf-8'))
    if len(new['nodes'])<=len(old['nodes']) or new['nodes'][:len(old['nodes'])]!=old['nodes']:raise ValueError('新素材不是原天气序列的追加版本')
    a=json.loads((old_root/'native_master.json').read_text(encoding='utf-8'))
    b=json.loads((new_root/'native_master.json').read_text(encoding='utf-8'))
    if any(a[k]!=b[k] for k in ('shape','extent','crs')):raise ValueError('不能在保留编辑时自动改变天气网格')
    lookup={i['path']:i for i in new['files']}
    for item in old['files']:
        if not item['path'].startswith('assets/'):continue
        path=item['path']
        component=Path(path).parts[1]
        if component in new.get('static_components',[]):path=f'assets/{component}/weather_0001.'+path.rsplit('.',1)[-1]
        if path not in lookup or lookup[path]['sha256']!=item['sha256']:raise ValueError('原时次图层发生变化，请单独审核替换，不自动追加')
    return True
