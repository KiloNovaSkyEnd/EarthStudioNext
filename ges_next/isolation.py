"""All Next mutations are contained within its own workspace or user profile."""
import json
import os
from pathlib import Path
from .path_identity import canonical

ROOT=Path(__file__).resolve().parents[1]


def require_writable(path, *, workspace=ROOT, protected=None, user_data=None):
    target=canonical(path)
    workspace=canonical(workspace)
    if protected is None:
        config=workspace/'protected_roots.json'
        protected=json.loads(config.read_text(encoding='utf-8'))['read_only_roots'] if config.exists() else []
    for root in protected:
        root=canonical(root)
        if target==root or root in target.parents:
            raise ValueError('旧版软件与归档只读；请使用新版独立工作目录。')
    if user_data is None:
        user_data=Path(os.environ.get('LOCALAPPDATA',str(workspace/'data')))/'Deepsky'/'EarthStudioNext'
    user_data=canonical(user_data)
    registry=user_data/'storage_locations.json'
    allowed=[workspace,user_data]
    if registry.is_file():allowed.extend(canonical(p) for p in json.loads(registry.read_text(encoding='utf-8')))
    if not any(target==root or root in target.parents for root in allowed):
        raise ValueError('请在软件中选择项目数据目录后再制作；外部归档可只读查看。目标：'+str(target)+'；允许：'+str(allowed))
    return target
