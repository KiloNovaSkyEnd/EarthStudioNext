"""M16 read-only preview adapter: original weather service plus immutable local audition media."""
import argparse
import re
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',type=Path,required=True)
    parser.add_argument('--materials',type=Path,required=True)
    parser.add_argument('--music',type=Path,required=True)
    parser.add_argument('--ui',type=Path,required=True)
    parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args()
    sys.path.insert(0,str(args.engine.resolve()))
    from ges_next.preview_server import handler
    music=args.music.resolve()
    class LocalHandler(handler(args.materials.resolve(),args.ui.resolve())):
        def translate_path(self,path):
            name=path.split('?',1)[0]
            if name.startswith('/music-assets/'):
                filename=name[len('/music-assets/'):]
                if re.fullmatch(r'[a-f0-9]{64}\.(wav|mp3)',filename):
                    target=music/filename
                    if target.resolve().parent==music:return str(target)
                return str(args.ui/'__denied__')
            return super().translate_path(path)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),LocalHandler)
    print(f'http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    finally:server.server_close()

if __name__=='__main__':main()
