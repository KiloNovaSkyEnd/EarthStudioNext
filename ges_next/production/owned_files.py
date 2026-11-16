"""Strict job subdirectory ownership and identity-locked Windows file deletion."""
import hashlib
import contextvars
import os
from pathlib import Path
import stat
import time
from ges_next.path_identity import canonical,normal_namespace

CLEANUP=contextvars.ContextVar('protected_owned_cleanup',default=None)


class CleanupSession:
    """Hash owned inputs once while Windows denies writers and replacements.

    Keep the original handle-based final identity/path/deletion checks. Files
    beyond the bounded handle budget, or temporarily busy files, use the
    existing repeated-hash path instead.
    """
    def __init__(self,max_files=256):
        if type(max_files) is not int or not 0<=max_files<=256:raise ValueError('Cleanup handle limit must be0..256')
        self.max_files=max_files;self.files={};self.token=None
        self.hash_reads=0;self.snapshot_hits=0;self.protected_deletions=0;self.fallbacks=0

    def __enter__(self):
        if CLEANUP.get() is not None:raise RuntimeError('Nested cleanup session')
        self.token=CLEANUP.set(self);return self

    def __exit__(self,*exc):
        try:
            for stream,_ in self.files.values():stream.close()
        finally:
            self.files.clear();CLEANUP.reset(self.token)

    def snapshot(self,path):
        path=Path(path).resolve()
        if path in self.files:
            stream,expected=self.files[path]
            if stamp(os.fstat(stream.fileno()),expected['sha256'])!=expected:
                raise ValueError('Pinned cleanup input identity changed')
            self.snapshot_hits+=1;return expected.copy()
        if len(self.files)>=self.max_files:
            self.fallbacks+=1;return None
        import ctypes,msvcrt
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
        handle=kernel.CreateFileW(str(path),0x80010000,1,None,3,0x00200000,None)
        if handle==ctypes.c_void_p(-1).value:
            error=ctypes.WinError(ctypes.get_last_error())
            if getattr(error,'winerror',None) in (5,32,33):
                self.fallbacks+=1;return None
            raise error
        stream=os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY),'rb')
        try:
            before=os.fstat(stream.fileno());sha=hashlib.file_digest(stream,'sha256').hexdigest();after=os.fstat(stream.fileno())
            if stamp(before,sha)!=stamp(after,sha):raise ValueError('Input changed while pinning cleanup identity')
            expected=stamp(after,sha)
        except BaseException:stream.close();raise
        self.files[path]=(stream,expected);self.hash_reads+=1
        return expected.copy()

    def delete(self,path,expected):
        path=Path(path).resolve()
        if path not in self.files:return False
        stream,pinned=self.files[path]
        if pinned!=expected:raise ValueError('Pinned cleanup input differs from deletion plan')
        _dispose_verified(stream,path,expected,pinned['sha256'])
        stream.close();del self.files[path];self.protected_deletions+=1
        return True

    def summary(self):
        return dict(pinned_hash_reads=self.hash_reads,reused_snapshots=self.snapshot_hits,
            protected_deletions=self.protected_deletions,fallbacks=self.fallbacks,maximum_pinned_files=self.max_files)


def cleanup_session():return CLEANUP.get() if os.name=='nt' else None


def owned_path(root, path, role):
    from ges_next.isolation import require_writable
    root=Path(normal_namespace(Path(root).absolute())); path=Path(normal_namespace(Path(path).absolute()))
    allowed=root/('raw' if role=='l1' else 'scratch')
    if '..' in path.parts or canonical(path) != path or not path.is_relative_to(allowed):
        raise ValueError(f'输入路径归属检查未通过，保留文件并停止本时次。作业目录：{root}；允许目录：{allowed}；输入：{path}；实际路径：{path.resolve()}')
    require_writable(path)
    for parent in [path,*path.parents]:
        if parent.exists():
            value=parent.lstat()
            if parent.is_symlink() or getattr(value,'st_file_attributes',0) & 0x400:
                raise ValueError('Reparse/link input paths are not reclaimable')
        if parent==root: break
    return path


def stamp(value, sha256):
    if not stat.S_ISREG(value.st_mode): raise ValueError('Only regular files can be reclaimed')
    return dict(bytes=value.st_size,mtime_ns=value.st_mtime_ns,device=str(value.st_dev),inode=str(value.st_ino),
                links=value.st_nlink,sha256=sha256)


def snapshot(path):
    path=Path(path)
    session=cleanup_session()
    if session is not None:
        value=session.snapshot(path)
        if value is not None:return value
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno()); sha=hashlib.file_digest(stream,'sha256').hexdigest(); after=os.fstat(stream.fileno())
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError('Input changed while checking identity')
    return stamp(after,sha)


def delete_verified(path, expected):
    """Retry only transient Windows sharing/lock conflicts, with all gates intact."""
    deadline=time.monotonic()+30
    delay=.05
    while True:
        try:return _delete_verified_once(path,expected)
        except PermissionError as error:
            code=getattr(error,'winerror',None)
            if code not in (32,33):raise
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise PermissionError(error.errno,'Owned cleanup file still busy after30s; input retained',str(path),code) from error
            time.sleep(min(delay,remaining));delay=min(delay*2,1)


def _delete_verified_once(path, expected):
    path=Path(path)
    if expected['links'] != 1: raise ValueError('Hardlinked/shared file retained')
    if os.name != 'nt':
        # Windows is the production target; portable tests still recheck identity.
        if snapshot(path) != expected: raise ValueError('Input changed before deletion')
        path.unlink(); return
    session=cleanup_session()
    if session is not None and session.delete(path,expected):return
    import ctypes
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
    kernel.SetFileInformationByHandle.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_ulong]
    kernel.GetFinalPathNameByHandleW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong]
    handle=kernel.CreateFileW(str(path),0x80010000,1,None,3,0x00200000,None)  # READ|DELETE, shareREAD only, open-reparse-point.
    if handle==ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    with os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY),'rb') as stream:
        value=os.fstat(stream.fileno()); sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if stamp(value,sha) != expected: raise ValueError('Input changed before deletion')
        _dispose_verified(stream,path,expected,sha)


def _dispose_verified(stream,path,expected,sha):
    import ctypes,msvcrt
    if stamp(os.fstat(stream.fileno()),sha)!=expected:raise ValueError('Input changed before deletion')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_ulong]
    kernel.GetFinalPathNameByHandleW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong]
    handle=msvcrt.get_osfhandle(stream.fileno());final=ctypes.create_unicode_buffer(32768)
    size=kernel.GetFinalPathNameByHandleW(handle,final,len(final),0)
    if not size or Path(normal_namespace(final.value))!=Path(normal_namespace(path)):
        raise ValueError('Opened input path differs')
    disposition=ctypes.c_ubyte(1)
    if not kernel.SetFileInformationByHandle(handle,4,ctypes.byref(disposition),ctypes.sizeof(disposition)):
        raise ctypes.WinError(ctypes.get_last_error())
