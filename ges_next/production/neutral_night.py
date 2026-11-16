"""Content-bound neutral reference cache; exact existing pixel/encoding formula."""
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image
from .assets import digest,write_json,record
from ..algorithms.night_modes import neutral_ground_background
from ..pipeline.locking import exclusive
Image.MAX_IMAGE_PIXELS=500_000_000

def ground(source,work):
    source=Path(source);work=Path(work)
    settings=json.loads((work/'shared_cache.json').read_text(encoding='utf-8'))
    from ..isolation import require_writable
    shared=require_writable(settings['path'])
    quality=settings['quality']
    if type(quality) is not int or not 1<=quality<=100:raise ValueError('Invalid neutral JPEG quality')
    identity=dict(source_sha256=digest(source),shape=[11000,11000,3],dtype='uint8',
        formula_sha256=digest(Path(neutral_ground_background.__code__.co_filename)),
        quality=quality,subsampling=0,optimize=False)
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    folder=shared/'neutral-reference-v1'/key;folder.mkdir(parents=True,exist_ok=True)
    receipt=folder/'receipt.json';array=folder/'ground.npy';jpeg=folder/'night.jpg'
    with exclusive(folder/'create.lock',wait=True):
        if not receipt.exists():
            if array.exists() or jpeg.exists():raise ValueError('Unverified neutral reference cache preserved')
            part=folder/'ground.npy.part'
            if part.exists():raise ValueError('Partial neutral reference preserved')
            output=np.lib.format.open_memmap(part,mode='w+',dtype='u1',shape=(11000,11000,3))
            with Image.open(source) as image:
                if image.size!=(11000,11000) or image.mode!='RGB':raise ValueError('Neutral source grid differs')
                image.load()
                for y in range(0,11000,250):
                    stop=min(y+250,11000)
                    rgb=np.asarray(image.crop((0,y,11000,stop)),np.float32)/255
                    output[y:stop]=np.uint8(np.rint(np.clip(neutral_ground_background(rgb),0,1)*255))
            output.flush();output._mmap.close();part.replace(array)
            pixels=np.load(array,mmap_mode='r')
            temp=folder/'night.jpg.part'
            # Use the exact formal encoder, including decode validation.
            from .jpeg_layers import encode_jpeg
            encode_jpeg(folder,'night.jpg',pixels,quality,'shared-static-night-background')
            pixels._mmap.close()
            write_json(receipt,dict(identity=identity,array_sha256=digest(array),jpeg_sha256=digest(jpeg)))
        proof=json.loads(receipt.read_text(encoding='utf-8'))
        if proof['identity']!=identity or proof['array_sha256']!=digest(array) or proof['jpeg_sha256']!=digest(jpeg):
            raise ValueError('Neutral reference cache identity changed')
    result=np.load(array,mmap_mode='r')
    if result.shape!=(11000,11000,3) or result.dtype!=np.uint8:raise ValueError('Neutral cache dtype/grid changed')
    return result

def materialize(pixels,output,relative):
    from .static_night import materialize as share
    folder=Path(pixels.filename).parent;source=folder/'night.jpg'
    proof=json.loads((folder/'receipt.json').read_text(encoding='utf-8'))
    if digest(source)!=proof['jpeg_sha256']:raise ValueError('Neutral JPEG changed')
    item=record(folder,source,'shared-static-night-background',[11000,11000])
    item.update(encoding='JPEG',quality=proof['identity']['quality'],subsampling='4:4:4',colour_space='display sRGB',lossless=False)
    return share(source,output,relative,item,link=True)


def enabled_for(work,utc,mode,config_path=None):
    """Apply only at new supported job boundaries, never rewrite an old job."""
    work=Path(work).resolve()
    config_path=Path(config_path) if config_path is not None else Path(__file__).resolve().parents[2]/'resources/performance/neutral_reference_activation.json'
    if not config_path.exists():return False
    config=json.loads(config_path.read_text(encoding='utf-8'))
    if config.get('enabled') is not True:return False
    if config.get('schema')!='earthstudio.neutral_reference.activation.v1':raise ValueError('Unknown neutral reference activation')
    package=next((p for p in (work,*list(work.parents)[:3]) if (p/'job.json').is_file()),None)
    if package is None:raise ValueError('Neutral reference lacks job binding')
    path=package/'job.json';job=json.loads(path.read_text(encoding='utf-8'))
    if job.get('utc')!=utc or job.get('night_recipe',{}).get('mode')!=mode:raise ValueError('Neutral reference job identity mismatch')
    return (job.get('quality')==95 and job.get('night_metres')==1000 and mode in ('ai-vis','ai-vis-ir')
            and path.stat().st_mtime_ns>=config['activated_ns']
            and str(package) not in config.get('excluded_packages',[]))
