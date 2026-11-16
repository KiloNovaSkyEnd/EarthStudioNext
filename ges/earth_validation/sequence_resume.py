"""Verify committed sequence pixels once, without recomputing all source disks."""
import json
from pathlib import Path
from PIL import Image
from .archive import sha
from .project import save


def verify(root):
    root=Path(root); report=root/'reports/stock_sequence.json'
    if not report.is_file(): return False
    record=json.loads(report.read_text(encoding='utf-8'))
    plan=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    frames=record.get('frames',[])
    if not record.get('complete_sequence') or len(frames)!=73: return False
    if [frame['nominal_utc'] for frame in frames]!=plan['frames']: return False
    receipt=root/'reports/completed_sequence_receipt.json'
    identity={'sequence_sha256':sha(report),'inventory_sha256':sha(root/'inventory.json')}
    if receipt.is_file():
        previous=json.loads(receipt.read_text(encoding='utf-8'))
        if previous['identity']!=identity: raise ValueError('Completed sequence identity changed; preserved')
        for item in previous['files']:
            if sha(Path(item['file']))!=item['sha256']:
                raise ValueError('Completed sequence pixels/metadata changed; preserved')
        return True
    files={}
    for frame in frames:
        path=Path(frame['file'])
        if not path.is_relative_to(root/'processed'): raise ValueError('Sequence file outside processed directory')
        with Image.open(path) as image:
            if image.size!=(4096,2048): raise ValueError('Completed sequence image shape differs')
            image.verify()
        files[str(path)]=sha(path)
        for source in frame['sources']:
            metadata=Path(source)
            data=json.loads(metadata.read_text(encoding='utf-8'))
            if data.get('profile')!='satpy-stock-geocolor-soft-rim-v1' or data.get('night_navigation_version')!=2:
                raise ValueError('Completed sequence profile differs')
            files[str(metadata)]=sha(metadata)
    save(receipt,{'identity':identity,'files':[{'file':path,'sha256':digest} for path,digest in files.items()],
                  'scope':'Committed proxy PNGs and source metadata; not a new raw archive audit or visual acceptance'})
    return True
