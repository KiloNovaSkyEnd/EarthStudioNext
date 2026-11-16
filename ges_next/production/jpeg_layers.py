"""JPEG primary colour, lossless scalar masks, and explicit quality measurements."""
from pathlib import Path
import numpy as np
from PIL import Image
from .assets import record,digest

Image.MAX_IMAGE_PIXELS = 500_000_000  # Header/shape still checked against the selected grid.


def encode_jpeg(root, relative, pixels, quality=95, role='colour',resume=False):
    if type(quality) is not int or not 1 <= quality <= 100:
        raise ValueError('JPEG quality must be an integer1..100')
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[-1] != 3:
        raise ValueError('JPEG production input must be RGB8')
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not resume:
        raise FileExistsError('Committed JPEG preserved')
    part = path.with_name(path.name + '.part')
    Image.fromarray(pixels).save(part, format='JPEG', quality=quality, subsampling=0, optimize=False)
    with Image.open(part) as image:
        if image.size != (pixels.shape[1], pixels.shape[0]) or image.mode != 'RGB':
            raise ValueError('JPEG shape/mode differs')
        image.load()
    if path.exists():
        if digest(part)!=digest(path):raise FileExistsError('Uncommitted candidate differs; previous bytes preserved')
        part.unlink()
    else:part.replace(path)
    return {**record(root, path, role, list(pixels.shape[:2])), 'encoding': 'JPEG', 'quality': quality,
            'subsampling': '4:4:4', 'colour_space': 'display sRGB', 'lossless': False}


def encode_mask(root, relative, pixels, role,resume=False):
    if pixels.ndim != 2 or pixels.dtype not in (np.uint8, np.uint16):
        raise ValueError('Only lossless scalar masks are permitted here')
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not resume:
        raise FileExistsError(path)
    part = path.with_name(path.name + '.part')
    Image.fromarray(pixels).save(part, format='PNG', compress_level=3)
    with Image.open(part) as image:
        restored = np.asarray(image)
        if not np.array_equal(restored, pixels):
            raise ValueError('Mask round trip changed values')
    if path.exists():
        if digest(part)!=digest(path):raise FileExistsError('Uncommitted mask differs; previous bytes preserved')
        part.unlink()
    else:part.replace(path)
    return {**record(root, path, role, list(pixels.shape)), 'encoding': 'PNG', 'lossless': True}


def srgb_to_linear(value):
    value = np.asarray(value)
    return np.where(value <= .04045, value / 12.92, ((value + .055) / 1.055) ** 2.4)


def reconstruct(base, night, transmission, strength=1, tint=(1, 1, 1)):
    """Stock affine composition in enhanced display RGB; transfer applied afterwards."""
    return np.clip(base.astype(np.float32)/255 + night.astype(np.float32)/255 *
                   (transmission.astype(np.float32)/65535)[..., None] * strength * np.asarray(tint), 0, 1)
