"""Verify full native assembly and on-demand geography; not a visual acceptance substitute."""
import io,json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np,rasterio
from PIL import Image
from rasterio.windows import Window
from pyproj import Transformer
from ges_next.preview_server import native_tile
from ges_next.isolation import require_writable

folder=Path(sys.argv[1]);report=require_writable(Path(sys.argv[2]));meta=json.loads((folder/'native_master.json').read_text(encoding='utf-8'))
checks=[];valid=0
with rasterio.open(folder/'master.vrt') as master:
 assert master.shape==(22000,22000) and master.count==4
 assert abs(master.res[0]-500)<.01
 for item in meta['tiles']:
  path=folder/item['path']
  with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256']
  with rasterio.open(path) as tile:
   core=item['coreWindow'];row,col=core['row'],core['col'];sx,sy=core['sourceX'],core['sourceY']
   assert row in [0,5500,11000,16500] and col in [0,5500,11000,16500]
   for y,x in [(0,0),(5490,5490),(2745,2745)]:
    a=tile.read(window=Window(sx+x,sy+y,10,10));b=master.read(window=Window(col+x,row+y,10,10));assert np.array_equal(a,b)
   valid+=np.count_nonzero(tile.read(4,window=Window(sx,sy,5500,5500)))
   checks.append(dict(path=item['path'],row=row,col=col,pixel_windows_equal=True))
 assert len({(x['row'],x['col']) for x in checks})==16
 transform=Transformer.from_crs('EPSG:4326',master.crs,always_xy=True)
 locations=[]
 for lon,lat in [(130.42,17.94),(179,0),(-179,0),(-40,0),(100,-30)]:
  z=7;w=360/2**(z+1);h=180/2**z;x=int((lon+180)/w);y=int((90-lat)/h)
  px=min(511,int((lon-(-180+x*w))/w*512));py=min(511,int(((90-y*h)-lat)/h*512))
  data=np.asarray(Image.open(io.BytesIO(native_tile(folder/'master.vrt',z,x,y))))
  # Compare at the precise geographic tile pixel centre.
  plon=-180+x*w+(px+.5)*w/512;plat=90-y*h-(py+.5)*h/512
  mx,my=transform.transform(plon,plat);rr,cc=master.index(mx,my) if np.isfinite(mx) and np.isfinite(my) else (-1,-1)
  source=master.read(window=Window(cc,rr,1,1))[:,0,0] if 0<=rr<22000 and 0<=cc<22000 else np.zeros(4,np.uint8)
  if source[3]==0:source[:3]=0
  assert np.array_equal(data[py,px],source),(lon,lat,data[py,px],source)
  locations.append(dict(lon=lon,lat=lat,rgba=data[py,px].tolist(),native_nearest_equal=True))
 assert locations[1]['rgba'][3]>0 and locations[2]['rgba'][3]>0
 assert locations[3]['rgba'][3]==0
report.write_text(json.dumps(dict(utc=meta['utc'],shape=[22000,22000],pixel_grid_metres=500,tiles=checks,valid_pixels=int(valid),locations=locations,native_master_verified=True,full_globe_coverage=False,visual_quality_accepted=False),indent=2),encoding='utf-8')
print('PASS:16 native tiles, exact assembly, hashes, nearest geographic samples, antimeridian and missing hemisphere')
