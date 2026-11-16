"""Compare retained JPEG layers against same-grid stock reference in strips."""
from PIL import Image
import numpy as np
from ges_next.production.jpeg_layers import reconstruct


def measure(root, reference, support,night_path=None,strip_rows=64):
    if type(strip_rows) is not int or strip_rows<1:raise ValueError("Positive strip row count required")
    with Image.open(root/'assets/base.jpg') as a, Image.open(night_path or root/'assets/night.jpg') as b, Image.open(root/'assets/transmission.png') as w:
        a.load(); b.load(); w.load()
        absolute = squared = count = 0
        maximum = 0
        for row in range(0, reference.shape[0], strip_rows):
            end = min(row+strip_rows,reference.shape[0]); box=(0,row,reference.shape[1],end)
            actual = reconstruct(np.asarray(a.crop(box)), np.asarray(b.crop(box)), np.asarray(w.crop(box))) * 255
            selected = support[row:end] > 0
            difference = actual[selected] - reference[row:end][selected].astype(np.float32)
            absolute += float(np.abs(difference).sum(dtype=np.float64)); squared += float((difference**2).sum(dtype=np.float64)); count += difference.size
            maximum = max(maximum,float(np.abs(difference).max(initial=0)))
        mse=squared/max(count,1)
        result=dict(valid_rgb_mae=absolute/max(count,1), psnr_db=float(10*np.log10(255**2/max(mse,1e-20))),
                    max_channel_error=maximum, samples=count, scope='Full1kmH9 grid, JPEG colour+lossless16bit transmission; not a visual acceptance')

    # Release decoded images before a rare threshold recheck; do not hold two
    # full sets of11K Pillow buffers across the recursive verification.
    a.close();b.close();w.close()
    # Reproduce the original summation partition at decision boundaries.
    # This avoids a last-bit sum difference changing quality/sample decisions.
    if strip_rows!=256 and any(abs(result['psnr_db']-cutoff)<1e-8 for cutoff in (35,37)):
        return measure(root,reference,support,night_path=night_path,strip_rows=256)
    return dict(result,partition_rows=strip_rows)
