"""Publish complete JSON atomically despite brief Windows reader sharing locks."""
import json,os,tempfile,time
from pathlib import Path


def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # Each publisher owns its partial; concurrent writers cannot truncate it.
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
            prefix=path.name+'.',suffix='.part',delete=False) as stream:
        temporary=Path(stream.name)
        json.dump(data,stream,ensure_ascii=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    deadline=time.monotonic()+5
    while True:
        try:
            temporary.replace(path)
            return
        except OSError as error:
            # Access/share/lock violations can be caused by a concurrent reader.
            # Keep the old complete document; permanent errors still fail closed.
            if getattr(error,'winerror',None) not in (5,32,33) or time.monotonic()>=deadline:
                raise
            time.sleep(.05)
