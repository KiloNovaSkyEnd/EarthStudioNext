"""NASA 2016 500m RGB tiles, lossless virtual mosaic and bounded reprojection.

Only supplies Satpy's existing static night-background input. No colour mapping.
"""
import json
import re
import time
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
import requests
from .archive import sha
from .project import check_disk, save

DOCUMENTATION = 'https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/'
TILE_IDS = tuple(f'{col}{row}' for row in (1, 2) for col in 'ABCD')


def expected_bounds(tile):
    col, row = 'ABCD'.index(tile[0]), int(tile[1])-1
    return (-180+90*col, -90*row, -90+90*col, 90-90*row)


def validate_tile(path, tile):
    with rasterio.open(path) as src:
        if (src.crs.to_epsg()!=4326 or (src.width,src.height,src.count)!=(21600,21600,3)
                or src.dtypes!=('uint8',)*3 or not np.allclose(src.bounds,expected_bounds(tile),atol=1e-7)):
            raise ValueError(f'Unexpected NASA {tile} georeferencing or RGB grid')
        return {'bounds': list(src.bounds), 'shape': [src.height,src.width],
                'pixel_degrees': list(src.res), 'crs': src.crs.to_string()}


def discover_urls():
    response = requests.get(DOCUMENTATION, timeout=(20,60))
    response.raise_for_status()
    # Exact product identity prevents accidentally selecting 2012 or grayscale.
    urls = re.findall(r'https://[^\s"<>]+/BlackMarble_2016_([ABCD][12])_geo\.tif', response.text)
    result = {}
    for tile in set(urls):
        match = re.search(r'https://[^\s"<>]+/BlackMarble_2016_'+tile+r'_geo\.tif',response.text)
        result[tile] = match.group(0)
    if set(result)!=set(TILE_IDS):
        raise ValueError('NASA page no longer exposes exactly the eight expected colour tiles')
    return result


def acquire(root, existing_d1=None):
    root = Path(root)
    folder = root/'raw/references/blackmarble_2016_500m'
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path=folder/'manifest.json'
    if manifest_path.is_file():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if {e['tile'] for e in manifest['tiles']}!=set(TILE_IDS):
            raise ValueError('Committed night mosaic inventory incomplete')
        for entry in manifest['tiles']:
            source=Path(entry['file'])
            if not source.is_file() or source.stat().st_size!=entry['bytes'] or sha(source)!=entry['sha256']:
                raise ValueError('Committed night reference changed; preserved')
            validate_tile(source,entry['tile'])
        return build_vrt(folder/'global_500m.vrt',manifest['tiles'])
    urls = discover_urls()
    entries = []
    for tile in TILE_IDS:
        path = folder/f'BlackMarble_2016_{tile}_geo.tif'
        if tile=='D1' and existing_d1 and Path(existing_d1).is_file():
            path = Path(existing_d1).resolve()  # share already downloaded immutable reference
        receipt = folder/f'{tile}.json'
        if receipt.exists():
            old = json.loads(receipt.read_text(encoding='utf-8'))
            if str(path)!=old['file'] or not path.is_file() or path.stat().st_size!=old['bytes'] or sha(path)!=old['sha256']:
                raise ValueError(f'Night background {tile} differs from committed receipt; preserved')
        if not path.is_file():
            with requests.head(urls[tile], headers={'Accept-Encoding':'identity'}, timeout=(20,60), allow_redirects=True) as head:
                head.raise_for_status()
                size = int(head.headers['Content-Length'])
                etag = head.headers.get('ETag')
            if not 0<size<1_000_000_000 or not etag:
                raise ValueError('Night tile failed size/identity preflight')
            check_disk(root,size)
            part = path.with_suffix('.tif.part')
            origin = part.with_suffix('.origin.json')
            identity = {'url':urls[tile], 'bytes':size, 'etag':etag}
            if part.exists() and (not origin.exists() or json.loads(origin.read_text())!=identity):
                raise ValueError('Unidentified partial night tile preserved')
            save(origin,identity)
            count = part.stat().st_size if part.exists() else 0
            if count>size:
                raise ValueError('Oversize night tile partial preserved')
            began = time.monotonic(); initial = count
            if count<size:
                headers = {'Accept-Encoding':'identity','If-Match':etag}
                if count: headers['Range'] = f'bytes={count}-'
                with requests.get(urls[tile],headers=headers,stream=True,timeout=(20,60)) as response:
                    response.raise_for_status()
                    if (count and (response.status_code!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {count}-'))
                            or int(response.headers.get('Content-Length',-1))!=size-count):
                        raise ValueError('Night tile response range/size mismatch')
                    with part.open('ab') as stream:
                        last = 0
                        for chunk in response.iter_content(1024*1024):
                            count += len(chunk)
                            if count>size: raise ValueError('Night tile body exceeds budget')
                            stream.write(chunk)
                            if time.monotonic()-last>3:
                                save(root/'reports/night_download_progress.json',{'tile':tile,'downloaded_bytes':count,
                                    'total_bytes':size,'bytes_per_second':(count-initial)/max(.001,time.monotonic()-began)})
                                last = time.monotonic()
                if count!=size: raise ValueError('Incomplete night tile retained')
            validate_tile(part,tile)
            part.replace(path)
        grid = validate_tile(path,tile)
        record = {'tile':tile,'file':str(path),'url':urls[tile], 'bytes':path.stat().st_size,
                  'sha256':sha(path),**grid}
        save(receipt,record); entries.append(record)
        print('NIGHT_REFERENCE',tile,record['bytes'],flush=True)
    vrt = build_vrt(folder/'global_500m.vrt',entries)
    save(folder/'manifest.json',{'reference_year':2016,'nominal_resolution_m':500,
        'display_rgb_not_calibrated_radiance':True,'documentation':DOCUMENTATION,
        'not_contemporaneous_weather':True,'tiles':entries,'vrt':str(vrt),
        'geographic_grid_verified':True,'coastline_control_points_verified':False})
    save(root/'reports/night_download_progress.json',{'stage':'completed','tiles':8,
        'total_bytes':sum(e['bytes'] for e in entries),'downloaded_bytes':sum(e['bytes'] for e in entries),
        'bytes_per_second':0,'vrt':str(vrt)})
    return vrt


def build_vrt(path, entries):
    if {e['tile'] for e in entries}!=set(TILE_IDS) or len(entries)!=8:
        raise ValueError('Global background requires all eight unique tiles')
    tree = ET.Element('VRTDataset',rasterXSize='86400',rasterYSize='43200')
    ET.SubElement(tree,'SRS').text='EPSG:4326'
    ET.SubElement(tree,'GeoTransform').text='-180, 0.004166666666666667, 0, 90, 0, -0.004166666666666667'
    for band,color in enumerate(('Red','Green','Blue'),1):
        node = ET.SubElement(tree,'VRTRasterBand',dataType='Byte',band=str(band))
        ET.SubElement(node,'ColorInterp').text=color
        for entry in entries:
            tile = entry['tile']; source = ET.SubElement(node,'SimpleSource')
            ET.SubElement(source,'SourceFilename',relativeToVRT='0').text=str(Path(entry['file']).resolve())
            ET.SubElement(source,'SourceBand').text=str(band)
            ET.SubElement(source,'SrcRect',xOff='0',yOff='0',xSize='21600',ySize='21600')
            ET.SubElement(source,'DstRect',xOff=str('ABCD'.index(tile[0])*21600),
                          yOff=str((int(tile[1])-1)*21600),xSize='21600',ySize='21600')
    path = Path(path); temporary = path.with_suffix('.vrt.part')
    ET.ElementTree(tree).write(temporary,encoding='utf-8',xml_declaration=True)
    if path.exists() and path.read_bytes()==temporary.read_bytes():
        # Stable identity keeps immutable grid caches reusable after a job handoff.
        temporary.unlink()
        return path
    temporary.replace(path)
    return path


def read_on_area(path, area, cache_root=None,out=None):
    """GDAL windowed source reads; never materializes the 11GB global RGB array."""
    path = Path(path)
    proxy = path.parent/'night_proxy_8km.tif'
    if path.name=='global_500m.vrt' and area.crs.is_projected and min(abs(area.pixel_size_x),abs(area.pixel_size_y))>=7000 and proxy.is_file():
        path = proxy
    if cache_root is not None:
        from .night_cache import read
        return read(path,area,cache_root,read_on_area)
    transform = from_bounds(*area.area_extent,area.width,area.height)
    with rasterio.open(path) as source:
        if area.width*area.height>=5_000_000 and area.crs.is_projected and source.crs.to_epsg()==4326:
            from .night_navigation import sample
            values=sample(source,area,out=out)
            if not any(np.any(values[:,row:row+512]>0) for row in range(0,area.height,512)):
                raise ValueError('Full-disk night navigation produced no real source values')
            return values
        with WarpedVRT(source,crs=area.crs,transform=transform,width=area.width,height=area.height,
            resampling=Resampling.nearest,tolerance=1e-9,dtype='float32',nodata=np.nan,warp_mem_limit=64) as warped:
            # Reading a large full geostationary disk in one call can make
            # GDAL skip valid source coverage and return an all-zero image.
            # Explicit bounded windows also retain accurate limb navigation.
            values=out if out is not None else np.empty((3,area.height,area.width),np.float32)
            for row in range(0,area.height,512):
                for col in range(0,area.width,512):
                    h=min(512,area.height-row); w=min(512,area.width-col)
                    values[:,row:row+h,col:col+w]=warped.read([1,2,3],window=Window(col,row,w,h))
    if (area.crs.is_projected and area.width>=3000 and area.height>=3000 and
        area.area_extent[0]<-2_000_000 and area.area_extent[2]>2_000_000 and not np.any(values>0)):
        raise ValueError('Full sensor disk night reference is unexpectedly empty; output must not be committed')
    return values


def make_proxy(vrt):
    """One shared nearest 1:16 reference proxy; full native files stay intact."""
    vrt = Path(vrt); output = vrt.parent/'night_proxy_8km.tif'
    if output.exists():
        with rasterio.open(output) as cached:
            if cached.shape!=(2700,5400) or cached.crs.to_epsg()!=4326:
                raise ValueError('Existing night proxy differs; preserved')
        return output
    values = np.zeros((3,2700,5400),np.uint8)
    manifest = json.loads((vrt.parent/'manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['tiles']:
        with rasterio.open(entry['file']) as src:
            reduced = src.read(out_shape=(3,1350,1350),resampling=Resampling.nearest)
        x='ABCD'.index(entry['tile'][0])*1350; y=(int(entry['tile'][1])-1)*1350
        values[:,y:y+1350,x:x+1350]=reduced
        print('NIGHT_PROXY',entry['tile'],flush=True)
    part=output.with_suffix('.part.tif')
    with rasterio.open(part,'w',driver='GTiff',width=5400,height=2700,count=3,
        dtype='uint8',crs='EPSG:4326',transform=from_bounds(-180,-90,180,90,5400,2700),
        tiled=True,compress='deflate') as dst:
        dst.write(values)
    part.replace(output)
    save(output.with_suffix('.json'),{'proxy':True,'downsample_factor':16,'method':'nearest',
        'native_sources_retained':True,'source_manifest_sha256':sha(vrt.parent/'manifest.json'),
        'sha256':sha(output),'shape':[2700,5400]})
    return output
