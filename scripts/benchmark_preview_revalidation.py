"""Bounded native-preview HTTP benchmark; three existing H9 footprints only."""
import json,time,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from ges_next.preview_server import handler,_cached_native_tile

root=Path(__file__).resolve().parents[1]
materials=root/'data/cesium_h9_motion_20261020'
server=ThreadingHTTPServer(('127.0.0.1',0),handler(materials))
worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
records=[]
try:
    for folder in ['20261020T1300Z','20261020T2240Z','20261021T0100Z']:
        url=f'http://127.0.0.1:{server.server_port}/data/{folder}/tiles/3/13/3.png'
        _cached_native_tile.cache_clear();start=time.perf_counter()
        with urlopen(url,timeout=120) as response:
            png=response.read();etag=response.headers['ETag']
        cold=time.perf_counter()-start
        start=time.perf_counter()
        with urlopen(url,timeout=120) as response:assert response.read()==png
        memory=time.perf_counter()-start
        # Browser must be able to reuse its image even after server LRU eviction.
        _cached_native_tile.cache_clear();start=time.perf_counter()
        try:urlopen(Request(url,headers={'If-None-Match':etag}),timeout=30)
        except HTTPError as error:assert error.code==304
        else:raise AssertionError('Expected not-modified response')
        revalidated=time.perf_counter()-start
        assert _cached_native_tile.cache_info().misses==0
        records.append(dict(utc_folder=folder,png_bytes=len(png),first_request_seconds=cold,memory_request_seconds=memory,browser_revalidation_seconds=revalidated,reprojection_after_eviction=False))
        print(json.dumps(records[-1]),flush=True)
finally:server.shutdown();server.server_close();worker.join()
out=root/'reports/h9_web_bridge/preview_cache_benchmark.json'
out.write_text(json.dumps(dict(tiles=records,scope='Three z3 footprints, not entire sequence or first-load acceleration'),indent=2),encoding='utf-8')
