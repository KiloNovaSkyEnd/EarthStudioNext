"""Candidate single-pass BZ2 decoding; not enabled in production before qualification."""
import bz2
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
from ges_next.production.assets import digest,write_json


@contextmanager
def locked_source(path):
    """Pin the source against Windows writers/replacement during hash and decode."""
    if os.name!='nt':
        with Path(path).open('rb') as stream:yield stream
        return
    import ctypes,msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
    handle=kernel.CreateFileW(str(Path(path).resolve()),0x80000000,1,None,3,0,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    with os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY),'rb') as stream:yield stream


class HashReader:
    def __init__(self,stream):self.stream=stream;self.sha=hashlib.sha256();self.bytes=0
    def read(self,size=-1):
        data=self.stream.read(size);self.sha.update(data);self.bytes+=len(data);return data


def decode(sources,destination,workers=None,metrics=None):
    from .policy import settings
    workers=settings()['decode_workers'] if workers is None else workers
    if type(workers) is not int or not 1<=workers<=8:raise ValueError('Decode workers must be1..8')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    def one(source):
        source=Path(source);began=time.perf_counter();target=destination/source.name.removesuffix('.bz2')
        receipt=target.with_suffix('.decode.json');part=target.with_suffix('.DAT.part')
        with locked_source(source) as raw:
            before=os.fstat(raw.fileno());identity=dict(source=str(source.resolve()),bytes=before.st_size)
            if target.exists():
                identity['sha256']=hashlib.file_digest(raw,'sha256').hexdigest()
                if not receipt.exists():raise ValueError('Decoded cache without receipt; preserved')
                old=json.loads(receipt.read_text(encoding='utf-8'))
                if old['input']!=identity or old['decoded_sha256']!=digest(target):raise ValueError('Decoded cache differs')
                reused=True;written=0
            else:
                reader=HashReader(raw);output_sha=hashlib.sha256();written=0
                with bz2.BZ2File(reader,'rb') as inp,part.open('wb') as out:
                    while block:=inp.read(1024*1024):
                        out.write(block);output_sha.update(block);written+=len(block)
                # BZ2File permits trailing non-BZ2 bytes. Hash all input bytes,
                # including any trailing bytes it did not consume, as before.
                while reader.read(1024*1024):pass
                if reader.bytes!=before.st_size:raise ValueError('Input length changed during decoding')
                identity['sha256']=reader.sha.hexdigest();reused=False
            after=os.fstat(raw.fileno())
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('Input changed during decoding')
            if not reused:
                # Retain an independent read-back check of installed bytes;
                # hashing intended writes alone must not certify a bad write.
                if digest(part)!=output_sha.hexdigest():
                    raise ValueError('Decoded write read-back differs; input preserved')
                write_json(receipt,dict(input=identity,decoded_sha256=output_sha.hexdigest()))
                part.replace(target)
        if metrics is not None:metrics.append(dict(source=source.name,seconds=time.perf_counter()-began,
            compressed_read_bytes=identity['bytes'],decoded_written_bytes=written,
            decoded_readback_bytes=written,cache_reused=reused))
        return target,identity
    with ThreadPoolExecutor(max_workers=workers) as pool:values=list(pool.map(one,sources))
    return [v[0] for v in values],[v[1] for v in values]
