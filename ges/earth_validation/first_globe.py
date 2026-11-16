"""Gate the expensive remaining sequence on a real complete-native-globe render."""
import json
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image
from .project import save
from .archive import sha


def qualify(root,blender,node,jobs,engine):
    root=Path(root); output=root/'exports/earth_native_only_v1'
    folder=output/'first_native_globe'; folder.mkdir(parents=True,exist_ok=True)
    report=folder/'qualification.json'; scene=output/'First_Native_Global_UTC1700.blend'
    image=folder/'frame_0001.png'
    if report.exists():
        old=json.loads(report.read_text(encoding='utf-8'))
        if old['scene_sha256']!=sha(scene) or old['image_sha256']!=sha(image):
            raise ValueError('First native globe qualification was changed; preserved')
        return old
    assets=folder/'assets.json'
    save(assets,{'nodes':[node],'cells':jobs,'frames':1,'hold':4,'native_only':True,
        'proxy_textures':False,'global_native_precomputed':True,'engine':str(engine),
        'qualification_only':True,'full_73_node_delivery_complete':False})
    scripts=Path(__file__).resolve().parents[2]/'scripts'
    with (root/'reports/first_native_globe.log').open('a',encoding='utf-8') as log:
        if not scene.exists():
            subprocess.run([str(blender),'-b','--python-exit-code','1','--python',
                str(scripts/'blender_native_earth.py'),'--','--root',str(root),'--assets',str(assets),
                '--scene-name',scene.name],stdout=log,stderr=subprocess.STDOUT,check=True)
        if not image.exists():
            subprocess.run([str(blender),'-b',str(scene),'--python-exit-code','1','--python',
                str(scripts/'blender_gpu_render.py'),'-o',str(folder/'frame_'),'-F','PNG','-f','1'],
                stdout=log,stderr=subprocess.STDOUT,check=True)
    with Image.open(image) as opened:
        values=np.asarray(opened.convert('RGB'))
    if values.shape!=(1080,1920,3) or np.count_nonzero(np.max(values,axis=2)>3)<10000:
        raise ValueError('Full native globe render empty or wrong size')
    result={'scene':str(scene),'scene_sha256':sha(scene),'image':str(image),'image_sha256':sha(image),
        'pages':len(jobs),'weather_nodes':1,'native_only':True,'render_passed':True,
        'full_73_node_delivery_complete':False,'visual_acceptance_passed':False,
        'limits':'Actual full native geographic loading/render gate; not 73-node completion or coastline acceptance'}
    save(report,result); return result
