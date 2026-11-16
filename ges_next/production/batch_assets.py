"""Each frame has its own asset evidence; Blender certification is explicit."""
import json,math
from pathlib import Path
from PIL import Image
from .assets import digest,verify_assets,write_json
from .template_certificate import copy_to
from .validation_session import load_image_once,active


def check_pixels(package,data):
    verify_assets(package,data['assets'])
    quality=data['quality']
    if not math.isfinite(quality['psnr_db']) or quality['psnr_db']<35 or quality['samples']<=0:
        raise ValueError('Per-frame full-grid quality check failed')
    if data['grid'].get('maximum_float_recomposition_error',float('inf'))>2e-5:
        raise ValueError('Stock recomposition parity missing/failed')
    for item in data['assets']:
        path=Path(package)/item['path']
        session=active();key=(str(path.resolve()),item['sha256'],item['role'],tuple(item['shape']))
        if session is not None and key in session.pixel_checks:continue
        with Image.open(path) as image:
            if list(image.size)[::-1]!=item['shape']:raise ValueError('Image grid differs')
            load_image_once(path,image)
            if item['role'] in ('stock-clouds-day-without-ground-background','shared-static-night-background'):
                if image.format!='JPEG' or image.mode!='RGB':raise ValueError('Expected actual RGB JPEG')
            elif item['role']=='stock-ground-transmission':
                if image.format!='PNG' or image.mode not in ('I;16','I;16L','I'):raise ValueError('Expected lossless 16bit transmission')
                low,high=image.getextrema()
                if low<0 or high>65535:raise ValueError('Transmission range invalid')
            elif item['role']=='actual-observation-support':
                if image.format!='PNG' or image.mode!='L':raise ValueError('Expected lossless support')
                counts=image.histogram()
                if sum(counts[1:255]):raise ValueError('Support must represent observed/non-observed pixels')
                if not counts[255]:raise ValueError('No actual observation support')
            else:raise ValueError('Unexpected image role')
        if session is not None:session.pixel_checks.add(key)


def issue(package,certificate):
    package=Path(package);data=json.loads((package/'commit.json').read_text(encoding='utf-8'))
    check_pixels(package,data)
    body=dict(schema='earthstudio.blender.template_assets.v1',utc=data['utc'],
        manifest_sha256=digest(package/'commit.json'),independent_of_l1=True,
        certificate=copy_to(package,certificate),
        checks=['full-image-decode','shape-and-encoding','lossless-mask-range','full-grid-stock-quality','asset-sha256'],
        limitation='This frame passed asset checks using a certified Blender template; this frame was not individually opened in Blender.')
    write_json(package/'asset_verification.json',body)
    return package/'asset_verification.json'
