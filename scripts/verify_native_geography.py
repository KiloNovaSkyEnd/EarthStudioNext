"""Render the actual shipped shader and original NASA reference; no weather claims."""
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_native_globe import NativeGlobeTests


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True,exist_ok=False)
    NativeGlobeTests.setUpClass()
    renderer = NativeGlobeTests()
    try:
        context = renderer.ctx
        texture = renderer.texture
        target = renderer.target
        source = ROOT/'native/EarthStudio.App/Preview/earth.jpg'
        with Image.open(source) as image:
            image = image.convert('RGB').transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            NativeGlobeTests.texture = context.texture(image.size,3,image.tobytes())
        NativeGlobeTests.texture.filter = texture.filter
        NativeGlobeTests.texture.repeat_x = False
        NativeGlobeTests.texture.repeat_y = False
        NativeGlobeTests.target = context.simple_framebuffer((641,641),components=4,dtype='f4')
        target.release();texture.release()
        views=[('Asia - 110E 20N',110,20),('Americas - 90W 20N',-90,20),('Africa - 20E 0N',20,0)]
        sheet=Image.new('RGB',(641*3,681),(12,18,28))
        for index,(label,lon,lat) in enumerate(views):
            rendered=renderer.render(lon,lat)
            image=Image.fromarray(np.uint8(np.rint(np.clip(rendered[::-1,:,:3],0,1)*255)))
            image.save(out/f'view_{index+1}.png')
            sheet.paste(image,(641*index,40))
            ImageDraw.Draw(sheet).text((641*index+15,12),label,fill=(240,240,240))
        sheet.save(out/'geography_views.png')
        (out/'verification.json').write_text(json.dumps({'renderer':context.info['GL_RENDERER'],
            'material':'original NASA 2004-10 static reference; no satellite weather',
            'coordinate_contract':'right-handed Y-up; east longitude maps to -Z; north=+Y',
            'views':views},indent=2),encoding='utf-8')
    finally:
        NativeGlobeTests.tearDownClass()


if __name__=='__main__':
    main()
