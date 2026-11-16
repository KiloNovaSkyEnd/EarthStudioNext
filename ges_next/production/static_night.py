"""Immutable projected night JPEG, shared by working packages and copied on export."""
import hashlib,json,os,shutil,stat
from pathlib import Path
import xml.etree.ElementTree as ET
from .assets import digest,write_json,record
from ..pipeline.locking import exclusive
from ..path_identity import canonical

ROLE='shared-static-night-background'
ROOT=Path(__file__).resolve().parents[2]

def reference_identity(source):
    source=canonical(source);files={source}
    for node in ET.parse(source).getroot().iter('SourceFilename'):
        file=Path(node.text)
        if node.get('relativeToVRT')=='1':file=source.parent/file
        files.add(canonical(file))
    manifest=source.parent/'manifest.json'
    return dict(vrt_sha256=digest(source),manifest_sha256=digest(manifest) if manifest.exists() else None,
        dependencies=[dict(path=str(p),bytes=p.stat().st_size,mtime_ns=p.stat().st_mtime_ns) for p in sorted(files)])

def materialize(source,output,relative,metadata,link=True):
    from ges_next.isolation import require_writable
    output=require_writable(output);source=Path(source);target=output/relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or not canonical(target).is_relative_to(canonical(output)):
        raise ValueError('Night asset path escapes package')
    target.parent.mkdir(parents=True,exist_ok=True)
    expected=metadata['sha256'];mode='existing'
    if source.is_symlink() or digest(source)!=expected:raise ValueError('Shared night asset changed')
    if target.exists():
        if target.is_symlink() or digest(target)!=expected:raise FileExistsError('Existing night asset differs')
    else:
        part=target.with_name(target.name+'.shared-part')
        if part.exists():raise FileExistsError('Interrupted night installation retained')
        source.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        try:
            if not link:raise OSError('Temporary parity image must remain independently reclaimable')
            os.link(source,part);mode='hardlink'
        except OSError:shutil.copyfile(source,part);mode='copy'
        if digest(part)!=expected:raise ValueError('Night materialization differs')
        part.replace(target)
    return {**metadata,**record(output,target,ROLE,metadata['shape']),'sharing':mode}

class StaticNight:
    def __init__(self,reference,grid,quality,cache=None):
        from ges_next.isolation import require_writable
        self.identity=dict(reference=reference,shape=grid['shape'],extent=grid['extent'],crs=grid['crs'],
            quality=quality,quantization='nan_to_num;rint;clip0..255;RGB8',code=digest(__file__))
        self.key=hashlib.sha256(json.dumps(self.identity,sort_keys=True).encode()).hexdigest()
        self.directory=require_writable((Path(cache) if cache else ROOT/'resources/cache/static_night_jpeg')/self.key)
        self.directory.mkdir(parents=True,exist_ok=True);self.path=self.directory/'night.jpg';self.receipt=self.directory/'receipt.json'

    def lookup(self):
        if not self.receipt.exists():return None
        value=json.loads(self.receipt.read_text(encoding='utf-8'))
        if value['identity']!=self.identity or value['asset']['shape']!=self.identity['shape'] or self.path.is_symlink() or not self.path.is_file() or digest(self.path)!=value['asset']['sha256']:
            raise ValueError('Static night cache identity/bytes changed; inputs preserved')
        return value

    def ensure(self,pixels=None):
        with exclusive(self.directory/'publish.lock',wait=True):
            value=self.lookup()
            if value:return value,True
            if pixels is None:raise ValueError('Static night cache disappeared before use')
            if list(pixels.shape[:2])!=self.identity['shape']:raise ValueError('Night pixels differ from cache grid')
            part=self.path.with_name(self.path.name+'.part')
            if part.exists() and (part.is_symlink() or part.stat().st_nlink!=1):raise ValueError('Unsafe shared night partial')
            from .jpeg_layers import encode_jpeg
            item=encode_jpeg(self.directory,'night.jpg',pixels,self.identity['quality'],ROLE,resume=True)
            value=dict(identity=self.identity,asset=item)
            self.path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
            write_json(self.receipt,value);return value,False
