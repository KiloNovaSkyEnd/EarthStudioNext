"""Budgeted byte-range archive for reading small subsets of large HDF5 objects.

Each cached block is exact provider bytes with source identity/range/hash, not a
complete NetCDF. Derived regional fields belong in processed storage separately.
"""
import hashlib
import io
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path
from .storage import preflight

_GROUP=None


def configure_group_budget(counter,lock,limit):
    global _GROUP
    _GROUP=(counter,lock,limit)


class RangeArchive(io.RawIOBase):
    def __init__(self,s3,bucket,key,size,etag,folder,cfg,max_bytes=100_000_000,block_size=262144):
        super().__init__();self.s3=s3;self.bucket=bucket;self.key=key;self.size=size;self.etag=etag
        self.folder=Path(folder);self.cfg=cfg;self.max_bytes=max_bytes;self.block_size=block_size;self.position=0
        self.blocks={};self.fetched=0;self.memory={}
        preflight(max_bytes,self.folder,cfg);self.folder.mkdir(parents=True,exist_ok=True)
        identity={'bucket':bucket,'key':key,'remote_size':size,'etag':etag,'block_size':block_size,
                  'kind':'partial raw byte-range archive, NOT a complete NetCDF product'}
        p=self.folder/'source.json'
        if p.exists() and json.loads(p.read_text())!=identity:raise ValueError('Raw range identity changed')
        if not p.exists():p.write_text(json.dumps(identity,indent=2),encoding='utf-8')

    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        target=offset if whence==0 else self.position+offset if whence==1 else self.size+offset
        if target<0:raise ValueError('Negative source offset')
        self.position=target;return target

    def _block(self,index):
        if index in self.memory:return self.memory[index]
        start=index*self.block_size;end=min(start+self.block_size,self.size)-1
        p=self.folder/f'{start:012d}_{end:012d}.bin';meta=p.with_suffix('.json')
        if p.exists():
            data=p.read_bytes()
            if not meta.exists():
                # Recover an interrupted sidecar commit only after comparing
                # against exact bytes of the same immutable source identity.
                r=self.s3.get_object(Bucket=self.bucket,Key=self.key,Range=f'bytes={start}-{end}',IfMatch=self.etag)
                check=r['Body'].read();r['Body'].close()
                if r.get('ContentRange')!=f'bytes {start}-{end}/{self.size}' or check!=data:
                    raise IOError('Uncommitted raw block differs from provider')
                meta.write_text(json.dumps({'start':start,'end':end,'sha256':hashlib.sha256(data).hexdigest()}),encoding='utf-8')
            m=json.loads(meta.read_text())
            if len(data)!=end-start+1 or hashlib.sha256(data).hexdigest()!=m['sha256']:
                raise IOError('Raw archived block failed size/hash verification')
        else:
            if self.fetched+end-start+1>self.max_bytes:raise RuntimeError('Regional range download cap exceeded')
            preflight(end-start+1,self.folder,self.cfg)
            n=end-start+1
            if _GROUP is not None:
                counter,lock,limit=_GROUP
                with lock:
                    if counter.value+n>limit:raise RuntimeError('Aggregate HSD plus L2 archive budget would exceed configured limit')
                    counter.value+=n
            committed=False
            try:
                response=self.s3.get_object(Bucket=self.bucket,Key=self.key,Range=f'bytes={start}-{end}',IfMatch=self.etag)
                if response.get('ContentRange')!=f'bytes {start}-{end}/{self.size}':raise IOError('Provider returned wrong source byte range')
                data=response['Body'].read();response['Body'].close()
                if len(data)!=n:raise IOError('Incomplete source range')
                partial=p.with_suffix('.'+uuid.uuid4().hex+'.part')
                with partial.open('xb') as f:f.write(data)
                os.replace(partial,p)
                meta.write_text(json.dumps({'start':start,'end':end,'sha256':hashlib.sha256(data).hexdigest()}),encoding='utf-8')
                committed=True
            finally:
                if not committed and _GROUP is not None:
                    with lock:counter.value-=n
            self.fetched+=len(data)
        self.blocks[index]=len(data);self.memory[index]=data
        return data

    def read(self,size=-1):
        if size is None or size<0:size=self.size-self.position
        size=min(size,self.size-self.position)
        if size<=0:return b''
        pieces=[];remaining=size
        while remaining:
            block=self.position//self.block_size;offset=self.position%self.block_size
            data=self._block(block);n=min(remaining,len(data)-offset)
            pieces.append(data[offset:offset+n]);self.position+=n;remaining-=n
        return b''.join(pieces)

    def readinto(self,buffer):
        data=self.read(len(buffer));buffer[:len(data)]=data;return len(data)

    def audit(self):
        return {'bucket':self.bucket,'key':self.key,'remote_bytes':self.size,'etag':self.etag,
                'block_size':self.block_size,'used_blocks':len(self.blocks),
                'used_archived_bytes':sum(self.blocks.values()),'new_bytes_this_run':self.fetched,
                'archive':str(self.folder.resolve()),'is_complete_raw_file':False}

    def prefetch_variable(self,variable,selection):
        """Fetch exactly the same aligned blocks concurrently, not neighboring data."""
        chunks=variable.chunks
        if chunks is None or len(selection)!=len(chunks):return
        selected=[]
        for sl,length,chunk in zip(selection,variable.shape,chunks):
            if isinstance(sl,int):
                selected.append([((sl%length)//chunk)*chunk]);continue
            start,stop,step=sl.indices(length)
            if step!=1:return
            selected.append(range((start//chunk)*chunk,stop,chunk))
        blocks=set()
        for coordinates in product(*selected):
            info=variable.id.get_chunk_info_by_coord(coordinates)
            if info.byte_offset is None or not info.size:continue
            blocks.update(range(info.byte_offset//self.block_size,(info.byte_offset+info.size-1)//self.block_size+1))
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(self._block,sorted(blocks)))
