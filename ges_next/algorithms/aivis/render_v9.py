"""Render 11000x11000 H9 full-disk nighttime V9 research JPEG.

The underlying seven/eight infrared bands are native 2 km. Doubling to the
existing software's 1 km grid does not create new satellite information.
"""

import ctypes
import gc
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parent
UTC = '2026-10-20T15:20:00Z'
DIR = ROOT / "full_disk_arrays"
PALETTE = np.array([[5, 8, 14], [46, 48, 54], [140, 144, 151], [231, 231, 231]], np.float32)
KNOTS = [0, .18, .5, 1]


def free_ram_gib():
    class S(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "free", "pt", "pf", "vt", "vf", "extra")]
    s = S()
    s.length = ctypes.sizeof(s)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.free/2**30


def smooth(x, lo, hi):
    t = np.clip((x-lo)/(hi-lo), 0, 1)
    return t*t*(3-2*t)


def palette(x):
    rgb = np.stack([np.interp(x, KNOTS, PALETTE[:, i]) for i in range(3)], axis=-1)
    return Image.fromarray(np.uint8(np.rint(np.clip(rgb, 0, 255))), "RGB")


def wait_ram(minimum):
    while free_ram_gib() < minimum:
        print(f"Waiting for RAM reserve {minimum} GiB; free={free_ram_gib():.2f}", flush=True)
        time.sleep(10)


def main():
    if hasattr(ctypes, "windll"):
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    wait_ram(8)
    b = {band: np.load(DIR / f"{band}.npy", mmap_mode="r") for band in ("B07", "B11", "B13", "B15")}
    ai = np.load(ROOT / "full_disk_ai_tiled_gray.npy", mmap_mode="r")
    if any(v.shape != (5500, 5500) for v in [*b.values(), ai]):
        raise RuntimeError("Unexpected native full-disk shape")
    partial = ROOT / "full_disk_v9_native_gray.npy.part"
    native_file = ROOT / "full_disk_v9_native_gray.npy"
    if partial.exists() or native_file.exists():
        raise RuntimeError("Full-disk output already exists; preserve prior test")
    native = np.lib.format.open_memmap(partial, mode="w+", dtype=np.float32, shape=(5500, 5500))
    image = Image.new("RGB", (5500, 5500), (0, 0, 0))
    began = time.perf_counter()
    for y0 in range(0, 5500, 250):
        y1 = y0+250
        top, bottom = max(0, y0-8), min(5500, y1+8)
        b07 = np.asarray(b["B07"][top:bottom], np.float32)
        b11 = np.asarray(b["B11"][top:bottom], np.float32)
        b13 = np.asarray(b["B13"][top:bottom], np.float32)
        b15 = np.asarray(b["B15"][top:bottom], np.float32)
        a = np.asarray(ai[top:bottom], np.float32)
        valid = np.isfinite(b13)&np.isfinite(a)
        safe13 = np.where(np.isfinite(b13), b13, 300)
        safe11 = np.where(np.isfinite(b11), b11, safe13)
        safe15 = np.where(np.isfinite(b15), b15, safe13)
        safe07 = np.where(np.isfinite(b07), b07, safe13)
        safeai = np.nan_to_num(a)
        h = np.clip((285-safe13)/100, 0, 1)**.72
        low = np.clip(np.where(np.isfinite(b07)&(safe13 >= 230), safe13-safe07, 0)/4, 0, 1)
        obs = np.clip(.025+.90*h+.55*low*(1-h), 0, 1)
        cold_w = .8*(1-smooth(safe13, 245, 275))*smooth(obs, .10, .37)
        cold = np.clip(obs*(1-cold_w)+np.clip(safeai, obs-.18, obs+.18)*cold_w, 0, 1)
        warm_gate = smooth(safe13, 242, 262)*(1-smooth(safe13, 285, 296))*smooth(safe11-safe13, -1.8, -.2)
        ai_warm = np.clip(safeai*1.12, 0, 1)**.80
        selected = np.clip(cold*(1-.70*warm_gate)+np.clip(ai_warm, cold-.14, cold+.18)*(.70*warm_gate), 0, 1)
        d_low = gaussian_filter(np.where(np.isfinite(b07), safe13-safe07, 0), sigma=1.2)
        low_support = smooth(d_low, .35, 2.3)*smooth(safe13, 270, 282)*(1-smooth(safe13, 291, 296))
        d_split = gaussian_filter(np.where(np.isfinite(b15), safe13-safe15, 0), sigma=1.2)
        warm_support = smooth(safe13, 246, 262)*(1-smooth(safe13, 281, 291))*smooth(d_split, 4, 8)*smooth(selected, .13, .31)
        v9 = np.clip(selected+.08*low_support+.04*warm_support, 0, 1)
        crop = slice(y0-top, y1-top)
        block = np.where(valid[crop], v9[crop], 0)
        native[y0:y1] = block
        image.paste(palette(block), (0, y0))
        del b07, b11, b13, b15, a, v9, selected, block
        wait_ram(5.5)
        print(f"render rows {y0}:{y1}, RAM free {free_ram_gib():.2f} GiB", flush=True)
    native.flush()
    del native
    gc.collect()
    partial.replace(native_file)
    native_preview = ROOT / "full_disk_v9_preview.png"
    image.resize((1100, 1100), Image.Resampling.BOX).save(native_preview)
    wait_ram(6)
    full = image.resize((11000, 11000), Image.Resampling.BILINEAR)
    output = ROOT / "full_disk_v9_11000.jpg"
    full.save(output, quality=95, subsampling=0)
    with Image.open(output) as check:
        if check.size != (11000, 11000):
            raise RuntimeError(f"Output size mismatch: {check.size}")
    result = {"utc": UTC, "source": "eight real H9 IR brightness-temperature bands, native 5500 grid",
              "ai": "public AI-VIS, bounded within V7 0.70 warm-cloud blend",
              "v9_additions": "measured B13-B07 low-cloud and B13-B15 warm-cloud cues",
              "output": str(output), "shape": [11000, 11000], "format": "JPEG RGB quality 95 no chroma subsampling",
              "output_bytes": output.stat().st_size, "seconds_render_and_encode": time.perf_counter()-began,
              "physical_cloud_resolution": "native 2 km IR; 11K grid is resampled, no claimed superresolution",
              "scope": "nighttime appearance study; no daytime truecolor/twilight composition or full time lapse"}
    (ROOT / "full_disk_v9_11k.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
