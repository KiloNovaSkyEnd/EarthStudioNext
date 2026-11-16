"""Repair the model's saturated, invalid-input limb ring in the research image.

Only the first five native 2 km pixels inside the observed footprint change.
The source inference and original JPEG are preserved for audit. This is a
display-footprint correction, not extra cloud detail or production code.
"""

import ctypes
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion, gaussian_filter

ROOT = Path(__file__).resolve().parent
SHAPE = (5500, 5500)
RIM_GAINS = (0.08, 0.30, 0.56, 0.78, 0.92)
PALETTE = np.array([[5, 8, 14], [46, 48, 54], [140, 144, 151], [231, 231, 231]], np.float32)
KNOTS = [0, .18, .5, 1]


def free_ram_gib():
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in ("total", "free", "pt", "pf", "vt", "vf", "extra")
        ]
    status = Status()
    status.length = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.free / 2**30


def correct_native_limb(ai, ir):
    if ai.shape != SHAPE or ir.shape != SHAPE:
        raise ValueError("Unexpected native grid")
    valid = np.isfinite(ir) & np.isfinite(ai)
    core = binary_erosion(valid, iterations=len(RIM_GAINS), border_value=0)
    if not core.any():
        raise ValueError("No interior disk support")
    # Inward information only: do not use the saturated outer predictions.
    weight = gaussian_filter(core.astype(np.float32), sigma=2.0)
    estimate = gaussian_filter(
        np.where(core, ai, 0).astype(np.float32), sigma=2.0
    )
    np.divide(estimate, weight, out=estimate, where=weight > 1e-6)
    corrected = np.where(valid, np.clip(ai, 0, 1), 0).astype(np.float32)
    ring_stats = []
    outside = valid
    for index, gain in enumerate(RIM_GAINS, 1):
        inside = binary_erosion(outside, border_value=0)
        ring = outside & ~inside
        before = np.asarray(ai[ring])
        corrected[ring] = np.clip(estimate[ring] * gain, 0, 1)
        after = corrected[ring]
        ring_stats.append(dict(
            native_ring=index, pixels=int(ring.sum()),
            mean_before=float(before.mean()), mean_after=float(after.mean()),
            fraction_above_0_7_before=float((before > 0.7).mean()),
            fraction_above_0_7_after=float((after > 0.7).mean()),
        ))
        outside = inside
    if not np.array_equal(outside, core):
        raise AssertionError("Repair support differs from intended five-pixel ring")
    if not np.array_equal(corrected[core], np.clip(ai[core], 0, 1)):
        raise AssertionError("A cloud pixel outside the limb ring changed")
    if ring_stats[0]["fraction_above_0_7_after"] != 0:
        raise AssertionError("Bright outer rim remains")
    return corrected, ring_stats


def main():
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x4000
    )
    if free_ram_gib() < 8:
        raise RuntimeError("Defer limb repair until at least 8 GiB RAM is free")
    ai = np.load(ROOT / "full_disk_ai_tiled_gray.npy", mmap_mode="r")
    ir = np.load(ROOT / "full_disk_arrays/B13.npy", mmap_mode="r")
    original = ROOT / "full_disk_pure_ai_vis_11000.jpg"
    backup = ROOT / "full_disk_pure_ai_vis_11000_original.jpg"
    preview = ROOT / "full_disk_pure_ai_vis_limb_fixed_preview.png"
    receipt = ROOT / "full_disk_pure_ai_vis_limb_repair.json"
    if backup.exists() or receipt.exists():
        raise FileExistsError("The research limb repair has already been run")
    if not original.exists():
        raise FileNotFoundError(original)

    began = time.perf_counter()
    corrected, ring_stats = correct_native_limb(ai, ir)

    image = Image.new("RGB", SHAPE[::-1], tuple(PALETTE[0].astype(int)))
    for y0 in range(0, SHAPE[0], 250):
        gray = corrected[y0:y0 + 250]
        channels = [np.interp(gray, KNOTS, PALETTE[:, channel])
                    for channel in range(3)]
        block = np.uint8(np.rint(np.clip(np.stack(channels, axis=-1), 0, 255)))
        image.paste(Image.fromarray(block, "RGB"), (0, y0))
        if free_ram_gib() < 6:
            raise RuntimeError("Stopped to preserve production RAM")
    image.resize((1100, 1100), Image.Resampling.BOX).save(preview)
    full = image.resize((11000, 11000), Image.Resampling.BILINEAR)
    temporary = ROOT / "full_disk_pure_ai_vis_11000_limb_fixed.part.jpg"
    full.save(temporary, quality=95, subsampling=0)
    with Image.open(temporary) as check:
        if check.size != (11000, 11000):
            raise AssertionError("Corrected full-disk size is wrong")
        check.verify()
    original.replace(backup)
    temporary.replace(original)
    data = dict(
        utc="2026-10-20T15:20:00Z", output=str(original),
        original=str(backup), native_shape=list(SHAPE), output_shape=[11000, 11000],
        cause="AI-VIS saturates where its convolutional input touches unobserved disk exterior",
        remedy="inward-only estimate and coverage taper over five native IR pixels",
        unchanged_interior=True, ring_stats=ring_stats,
        seconds=float(time.perf_counter() - began),
        qualification="research limb correction only; sequence and Blender validation pending",
    )
    receipt.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
