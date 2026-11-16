"""Reuse hashes only while Windows handles pin the exact files against mutation."""
import contextvars,hashlib,os
from pathlib import Path

CURRENT=contextvars.ContextVar('production_validation_session',default=None)


class ValidationSession:
    def __init__(self):self.files={};self.decoded=set();self.pixel_checks=set();self.token=None;self.hash_reads=0
    def __enter__(self):
        if CURRENT.get() is not None:raise RuntimeError('Nested validation session')
        self.token=CURRENT.set(self);return self
    def __exit__(self,*exc):
        try:
            for stream,_ in self.files.values():stream.close()
        finally:CURRENT.reset(self.token)

    def digest(self,path):
        path=Path(path).resolve()
        if path in self.files:return self.files[path][1]
        import ctypes,msvcrt
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
        # GENERIC_READ, share READ only: no writer or replacement can change the
        # file until every check and the cleanup decision in this session ends.
        handle=kernel.CreateFileW(str(path),0x80000000,1,None,3,0,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        stream=os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY),'rb')
        try:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        except BaseException:stream.close();raise
        self.files[path]=(stream,sha);self.hash_reads+=1;return sha


def active():return CURRENT.get() if os.name=='nt' else None


def load_image_once(path,image):
    session=active();key=(str(Path(path).resolve()),image.mode,image.size)
    # The asset must already be pinned and hashed before its decoded result may
    # be reused. Outside a protected session retain the ordinary full decode.
    if session is None or Path(path).resolve() not in session.files:
        image.load();return
    if key not in session.decoded:image.load();session.decoded.add(key)
