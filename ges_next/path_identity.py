"""Compare equivalent Win32 drive/UNC namespaces without weakening containment."""
from pathlib import Path
import re


def normal_namespace(value):
    text=str(value)
    if text.startswith('\\\\?\\UNC\\'):
        return '\\\\'+text[8:]
    if re.match(r'^\\\\\?\\[A-Za-z]:\\',text):
        return text[4:]
    # Device and volume GUID paths are not ordinary drive/UNC aliases.
    return text


def canonical(value):
    return Path(normal_namespace(Path(value).expanduser().resolve()))
