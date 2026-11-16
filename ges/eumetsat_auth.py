"""Local Windows DPAPI credential storage; never print credentials or tokens."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


def credential_path() -> Path:
    root=os.environ.get('LOCALAPPDATA')
    if not root:
        raise RuntimeError('Windows LOCALAPPDATA is unavailable')
    return Path(root)/'GlobalSatelliteEarthStudioNext'/'eumetsat_credentials.dpapi'


def _dpapi(data: bytes, decrypt=False) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('This credential store requires Windows DPAPI')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,
                       ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    kernel.LocalFree.restype=ctypes.c_void_p
    buffer=ctypes.create_string_buffer(data)
    incoming=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    outgoing=Blob()
    # CRYPTPROTECT_UI_FORBIDDEN; do not use machine-wide encryption scope.
    if not function(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing)):
        raise RuntimeError('Windows credential encryption/decryption failed')
    try:
        return ctypes.string_at(outgoing.data,outgoing.size)
    finally:
        kernel.LocalFree(ctypes.cast(outgoing.data,ctypes.c_void_p))


def save_credentials(key: str, secret: str, path: Path | None=None) -> None:
    if not key.strip() or not secret.strip():
        raise ValueError('Both consumer key and secret are required')
    payload=json.dumps({'consumer_key':key.strip(),'consumer_secret':secret.strip()}).encode('utf-8')
    encrypted=_dpapi(payload)
    path=path or credential_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_bytes(encrypted)
    temporary.replace(path)


def load_credentials(path: Path | None=None) -> tuple[str,str]:
    path=path or credential_path()
    if not path.is_file():
        raise FileNotFoundError('Run configure_eumetsat.bat to configure credentials locally')
    values=json.loads(_dpapi(path.read_bytes(),decrypt=True).decode('utf-8'))
    return values['consumer_key'],values['consumer_secret']


def authenticated_token(credentials=None):
    import eumdac
    from eumdac.logging import logger
    # EUMDAC debug logs may include token strings. Never enable those here.
    logger.disabled=True
    token=eumdac.AccessToken(credentials if credentials is not None else load_credentials())
    if not token.access_token:
        raise RuntimeError('EUMETSAT returned no token')
    return token
