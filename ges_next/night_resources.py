"""Shared read-only night reference, configured independently of disposable jobs."""
import json,os
from pathlib import Path
import xml.etree.ElementTree as ET

def settings():
 return Path(os.environ.get('LOCALAPPDATA',str(Path(__file__).resolve().parents[1]/'data')))/'Deepsky/EarthStudioNext/night_reference.json'

def validate(path):
 path=Path(path).expanduser().resolve()
 if not path.is_file():raise ValueError('夜景参考未找到。请在第4步的“共享夜景参考”设置全球参考VRT；不会先下载L1。')
 try:root=ET.parse(path).getroot()
 except ET.ParseError as error:raise ValueError('夜景参考VRT格式无效') from error
 shape=(int(root.get('rasterXSize','0')),int(root.get('rasterYSize','0')))
 if shape not in ((86400,43200),(43200,21600)):raise ValueError('需要全球500m或1km夜景VRT，不接受局部图或JPG成品替代。')
 transform=[float(v) for v in root.findtext('GeoTransform','').split(',')]
 expected=[-180,360/shape[0],0,90,0,-180/shape[1]]
 if len(transform)!=6 or any(abs(a-b)>1e-7 for a,b in zip(transform,expected)):raise ValueError('夜景参考全球经纬度网格不正确。')
 names=root.findall('.//SourceFilename')
 if not names:raise ValueError('夜景VRT没有实际素材依赖。')
 for node in names:
  source=Path(node.text or '')
  if node.get('relativeToVRT')=='1':source=path.parent/source
  if not source.is_file():raise ValueError('夜景VRT引用的文件已缺失：'+str(source))
 return path

def configure(path):
 path=validate(path);file=settings();file.parent.mkdir(parents=True,exist_ok=True)
 temp=file.with_suffix('.tmp');temp.write_text(json.dumps(dict(path=str(path))),encoding='utf-8');temp.replace(file)
 return path

def resolve(check_pixels=False,metres=1000):
 file=settings()
 if file.exists():
  path=validate(json.loads(file.read_text(encoding='utf-8'))['path'])
 else:
  name='global_500m.vrt' if metres==500 else 'global_1km.vrt'
  bundled=Path(__file__).resolve().parents[1]/'resources/references/blackmarble_2016_500m'/name
  if not bundled.is_file():raise ValueError('共享夜景参考缺失。请安装发布页的两个夜景资源包，或在第4步设置全球参考VRT。')
  path=validate(bundled)
 if metres==500 and ET.parse(path).getroot().get('rasterXSize')!='86400':raise ValueError('500m制作需要500m全球夜景源，不能放大1km参考')
 if check_pixels:
  import rasterio
  for node in ET.parse(path).getroot().findall('.//SourceFilename'):
   source=Path(node.text)
   if node.get('relativeToVRT')=='1':source=path.parent/source
   try:
    with rasterio.open(source) as dataset:dataset.read(1,window=((0,1),(0,1)))
   except rasterio.errors.RasterioError as error:raise ValueError('夜景参考无法读取，尚未下载L1：'+str(source)) from error
 return path
