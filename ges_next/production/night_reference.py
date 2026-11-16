"""Virtual1km area-average reference; never copies the global500m raster."""
from pathlib import Path
import xml.etree.ElementTree as ET


def reference_grid(source, target, metres):
    source, target = Path(source).resolve(), Path(target)
    if metres == 500:
        return source
    if metres != 1000:
        raise ValueError('Night reference must be nominal500m or1km')
    tree = ET.parse(source)
    root = tree.getroot()
    if (root.get('rasterXSize'), root.get('rasterYSize')) == ('43200','21600'):
        return source  # Already a configured global1km reference.
    if (root.get('rasterXSize'), root.get('rasterYSize')) != ('86400', '43200'):
        raise ValueError('Expected verified global500m reference grid')
    root.set('rasterXSize', '43200'); root.set('rasterYSize', '21600')
    transform = [float(v) for v in root.find('GeoTransform').text.split(',')]
    transform[1] *= 2; transform[5] *= 2
    root.find('GeoTransform').text = ','.join(map(str, transform))
    for band in root.findall('VRTRasterBand'):
        for node in band.findall('SimpleSource'):
            node.tag = 'AveragedSource'
            name = node.find('SourceFilename')
            path = Path(name.text)
            if name.get('relativeToVRT') == '1': path = source.parent / path
            name.text = str(path.resolve()); name.set('relativeToVRT', '0')
            rect = node.find('DstRect')
            for key in ['xOff', 'yOff', 'xSize', 'ySize']:
                value = int(rect.get(key))
                if value % 2: raise ValueError('Reference grid not2x aligned')
                rect.set(key, str(value // 2))
    target.parent.mkdir(parents=True, exist_ok=True)
    import io
    buffer=io.BytesIO()
    tree.write(buffer,encoding='utf-8',xml_declaration=True)
    payload=buffer.getvalue()
    if target.exists():
        if ET.canonicalize(target.read_text(encoding='utf-8'),strip_text=True)!=ET.canonicalize(payload.decode('utf-8'),strip_text=True):
            raise ValueError('Existing reference grid differs')
    else:
        target.write_bytes(payload)
    return target.resolve()
