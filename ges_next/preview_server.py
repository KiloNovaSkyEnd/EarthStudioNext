"""Development-only, loopback read-only Cesium + selected material directory."""
import argparse
import io
import hashlib
import xml.etree.ElementTree as ET
from functools import lru_cache
import re
from threading import BoundedSemaphore

_NATIVE_READS=BoundedSemaphore(2)
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit

UI=Path(__file__).resolve().parents[1]/'native/EarthStudio.App/Cesium'


def handler(materials, ui_root=UI):
    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self,path):
            name=unquote(urlsplit(path).path)
            root=materials if name.startswith('/data/') else ui_root
            relative=name[6:] if name.startswith('/data/') else name.lstrip('/')
            target=(root/relative).resolve()
            if target!=root and root not in target.parents: return str(ui_root/'__denied__')
            return str(target)
        def do_GET(self):
            self._tile_response=False
            # Only committed native masters under the selected materials root.
            match=re.fullmatch(r'/data/([A-Za-z0-9_-]+)/tiles/(\d+)/(\d+)/(\d+)\.png',urlsplit(self.path).path)
            if match and (materials/match[1]/'master.vrt').is_file() and (materials/match[1]/'manifest.json').is_file():
                folder,z,x,y=match.groups();z,x,y=map(int,(z,x,y))
                if not 0<=z<=8 or not 0<=x<2**(z+1) or not 0<=y<2**z:
                    self.send_error(404);return
                try:
                    master=materials/folder/'master.vrt'
                    signature=native_signature(master)
                    etag='"'+hashlib.sha256(f'{signature}:{z}:{x}:{y}:png512-v1'.encode()).hexdigest()+'"'
                    self._tile_response=True
                    if self.headers.get('If-None-Match')==etag:
                        self.send_response(304);self.send_header('ETag',etag);self.end_headers();return
                    with _NATIVE_READS:
                        data=_cached_native_tile(master,z,x,y,signature)
                    self.send_response(200);self.send_header('ETag',etag);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
                except ConnectionError:pass  # Includes Windows10053 on viewport/reload cancellation.
                except Exception as error:
                    self.log_error('Native tile failed: %s',error)
                    self.send_error(500,'Native tile unavailable')
                return
            super().do_GET()
        def list_directory(self,path):
            self.send_error(403,'Directory listing disabled')
        def end_headers(self):
            self.send_header('Cache-Control','private, max-age=0, must-revalidate' if getattr(self,'_tile_response',False) else 'no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            super().end_headers()
    return Handler


def native_signature(master):
    """Invalidate preview caches when a master or any referenced page changes."""
    master=Path(master).resolve();dependencies={master}
    if master.suffix.lower()=='.vrt':
        for element in ET.parse(master).iter('SourceFilename'):
            source=Path(element.text)
            dependencies.add((master.parent/source if element.get('relativeToVRT')=='1' else source).resolve())
    digest=hashlib.sha256()
    for path in sorted(dependencies):
        stat=path.stat();digest.update(f'{path}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
    return digest.hexdigest()


def native_tile(master,z,x,y):
    master=Path(master).resolve()
    return _cached_native_tile(master,z,x,y,native_signature(master))


@lru_cache(maxsize=128)
def _cached_native_tile(master,z,x,y,signature):
    """Read only the requested footprint from the retained sensor-native master."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject,Resampling
    from PIL import Image
    width=360/2**(z+1);height=180/2**z
    west=-180+x*width;north=90-y*height
    transform=from_bounds(west,north-height,west+width,north,512,512)
    pixels=np.zeros((4,512,512),np.uint8)
    with rasterio.open(master) as source:
        reproject(rasterio.band(source,[1,2,3,4]),pixels,src_transform=source.transform,src_crs=source.crs,dst_transform=transform,dst_crs='EPSG:4326',resampling=Resampling.nearest,src_alpha=4,dst_alpha=4,warp_mem_limit=32,num_threads=1)
    pixels[:3,pixels[3]==0]=0
    stream=io.BytesIO();Image.fromarray(pixels.transpose(1,2,0)).save(stream,format='PNG');return stream.getvalue()


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--materials',type=Path,required=True); p.add_argument('--port',type=int,default=8765); p.add_argument('--ui',type=Path,default=UI)
    args=p.parse_args(); materials=args.materials.resolve()
    if not (materials/'manifest.json').is_file(): raise ValueError('manifest.json required')
    ui_root=args.ui.resolve()
    if not (ui_root/'index.html').is_file(): raise ValueError('Local renderer index.html required')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler(materials,ui_root))
    print(f'http://127.0.0.1:{server.server_port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
