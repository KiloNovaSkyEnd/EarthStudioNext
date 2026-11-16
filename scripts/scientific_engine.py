"""Standalone scientific executable entry; GUI bridge uses stdin JSON."""
import sys
from ges.earth_validation import bootstrap  # noqa: F401; before scientific imports


if __name__=='__main__':
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
    if len(sys.argv)>1 and sys.argv[1]=='bridge':
        from ges.native_bridge import main
    else:
        from ges.earth_validation.__main__ import main
    main()
