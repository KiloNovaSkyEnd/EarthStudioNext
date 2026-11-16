"""Explicit 11K display derivative of retained 22K RGBA, not new observations."""
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np


def read_reduced_tiles(package, master, index):
    """Read independent RGBA cores together; avoid VRT per-band decode work."""
    from concurrent.futures import ThreadPoolExecutor
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import Window

    def tile_pixels(tile):
        core = tile['coreWindow']
        if any(core[name] % 2 for name in ['row', 'col', 'sourceX', 'sourceY', 'width', 'height']):
            raise ValueError('Tile is not aligned to the2x area-reduction grid')
        path = Path(package) / 'assets' / Path(tile['path']).stem / f'weather_{index:04d}.tif'
        with rasterio.open(path) as image:
            values = image.read(window=Window(core['sourceX'], core['sourceY'], core['width'], core['height']),
                                out_shape=(4, core['height'] // 2, core['width'] // 2), resampling=Resampling.average)
        return core, np.moveaxis(values, 0, -1)

    result = np.empty((master['shape'][0] // 2, master['shape'][1] // 2, 4), dtype=np.uint8)
    with rasterio.Env(GDAL_CACHEMAX=128 * 1024 * 1024), ThreadPoolExecutor(max_workers=4) as pool:
        for core, values in pool.map(tile_pixels, master['tiles']):
            row, col = core['row'] // 2, core['col'] // 2
            result[row:row + values.shape[0], col:col + values.shape[1]] = values
    return result


def reduce_rgba2(pixels):
    """2x2 area average; alpha-weight RGB to avoid dark missing-data fringes."""
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 4 or any(n % 2 for n in pixels.shape[:2]):
        raise ValueError('Expected even-height/even-width RGBA8')
    height, width = pixels.shape[:2]
    groups = pixels.reshape(height // 2, 2, width // 2, 2, 4)
    alpha = groups[..., 3].astype(np.uint32)
    weights = alpha.sum(axis=(1, 3), dtype=np.uint32)
    result = np.zeros((height // 2, width // 2, 4), dtype=np.uint8)
    for channel in range(3):
        values = (groups[..., channel].astype(np.uint32) * alpha).sum(axis=(1, 3), dtype=np.uint32)
        result[..., channel] = ((values + weights // 2) // np.maximum(weights, 1)).astype(np.uint8)
    result[..., 3] = ((weights + 2) // 4).astype(np.uint8)
    return result


def source_vrt(master, package, index, target):
    """Address the sealed tile cores without resampling their pixels."""
    tree = ET.Element('VRTDataset', rasterXSize=str(master['shape'][1]), rasterYSize=str(master['shape'][0]))
    first = master['tiles'][0]
    ET.SubElement(tree, 'SRS').text = first['crs']
    ET.SubElement(tree, 'GeoTransform').text = ','.join(map(str, [first['extent'][0], first['transform'][0], 0,
                                                                  first['extent'][3], 0, first['transform'][4]]))
    for channel, color in enumerate(['Red', 'Green', 'Blue', 'Alpha'], 1):
        band = ET.SubElement(tree, 'VRTRasterBand', dataType='Byte', band=str(channel))
        ET.SubElement(band, 'ColorInterp').text = color
        for tile in master['tiles']:
            core = tile['coreWindow']
            source = ET.SubElement(band, 'SimpleSource')
            ET.SubElement(source, 'SourceFilename', relativeToVRT='0').text = str((Path(package) / 'assets' / Path(tile['path']).stem / f'weather_{index:04d}.tif').resolve())
            ET.SubElement(source, 'SourceBand').text = str(channel)
            ET.SubElement(source, 'SrcRect', xOff=str(core['sourceX']), yOff=str(core['sourceY']), xSize=str(core['width']), ySize=str(core['height']))
            ET.SubElement(source, 'DstRect', xOff=str(core['col']), yOff=str(core['row']), xSize=str(core['width']), ySize=str(core['height']))
    ET.ElementTree(tree).write(target, encoding='utf-8', xml_declaration=True)
