"""Calibrate full H9 disk one band/550 rows at a time into mmap arrays.

Independent research assets only. Monitors physical memory and stops before
the next band when the production reserve would be too small.
"""

import bz2
import hashlib,uuid
import ctypes
import gc
import json
from pathlib import Path
import shutil
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
UTC = "2026-10-20T15:20:00Z"
BANDS = ("B07", "B08", "B09", "B10", "B11", "B13", "B15", "B16")
RESERVE_GIB = 6


def free_gib():
    class S(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "free", "pt", "pf", "vt", "vf", "extra")]
    state = S()
    state.length = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        raise RuntimeError("Memory status unavailable")
    return state.free/2**30


def main():
    if hasattr(ctypes, "windll"):
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    while free_gib() < 8:
        print(f"Waiting for calibration RAM: {free_gib():.2f} GiB free; need >=8",flush=True);time.sleep(30)
    import dask
    import satpy
    target_dir = ROOT / "full_disk_arrays"
    decoded_dir = ROOT / "decoded_full"
    target_dir.mkdir(exist_ok=True)
    decoded_dir.mkdir(exist_ok=True)
    info = {"utc": UTC, "satellite": "Himawari-9",
            "shape": [5500, 5500], "priority": "below-normal", "bands": {}}
    proof_path=target_dir/'calibration.json'
    if proof_path.exists():
        old=json.loads(proof_path.read_text(encoding='utf-8'))
        if old.get('utc')!=UTC:raise ValueError('Calibration UTC changed')
        info['bands']=old.get('bands',{})
    def publish(complete=False):
        info['complete']=complete
        temp=proof_path.with_suffix('.tmp');temp.write_text(json.dumps(info,indent=2),encoding='utf-8');temp.replace(proof_path)
    def checksum(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    for band in BANDS:
        target = target_dir / f"{band}.npy"
        if target.exists() and not info['bands'].get(band,{}).get('array_sha256'):
            target.rename(target.with_name(target.name+'.unverified-'+uuid.uuid4().hex))
        if target.exists():
            if checksum(target)!=info['bands'][band]['array_sha256']:raise ValueError('Calibrated array changed: '+band)
            existing = np.load(target, mmap_mode="r")
            if existing.shape != (5500, 5500):
                raise RuntimeError(f"Unexpected existing full-disk array {target}")
            del existing
            print("existing", target.name, flush=True)
            continue
        while free_gib() < RESERVE_GIB+1:
            print(f"Waiting before {band}: free RAM {free_gib():.2f} GiB",flush=True);time.sleep(30)
        inputs = []
        for seg in range(1, 11):
            sources = list(RAW_DIR.glob(f"*_{band}_*S{seg:02d}10.DAT.bz2"))
            if len(sources) != 1:
                raise RuntimeError(f"Expected one {band} segment {seg}: got {len(sources)}")
            source = sources[0]
            original_decoded = ROOT / "decoded" / source.name.removesuffix(".bz2")
            decoded = original_decoded if original_decoded.exists() else decoded_dir / source.name.removesuffix(".bz2")
            if not decoded.exists():
                part = decoded.with_suffix(decoded.suffix+".part")
                if part.exists():
                    raise RuntimeError(f"Preserved partial decode: {part}")
                with bz2.open(source, "rb") as inp, part.open("wb") as out:
                    shutil.copyfileobj(inp, out, 1024*1024)
                part.replace(decoded)
            inputs.append(str(decoded))
        began = time.perf_counter()
        partial = target.with_suffix(".npy.part")
        if partial.exists():partial.rename(partial.with_name(band+'.interrupted-'+uuid.uuid4().hex+'.npy'))
        with dask.config.set(scheduler="single-threaded"):
            scene = satpy.Scene(reader="ahi_hsd", filenames=inputs)
            scene.load([band])
            data = scene[band]
            if data.shape != (5500, 5500) or data.attrs.get("units") != "K":
                raise RuntimeError(f"Unexpected calibration for {band}: {data.shape}")
            output = np.lib.format.open_memmap(partial, mode="w+", dtype=np.float32, shape=(5500, 5500))
            for seg in range(10):
                y0, y1 = seg*550, (seg+1)*550
                strip = np.asarray(data.data[y0:y1, :].compute(), np.float32)
                if strip.shape != (550, 5500) or np.isfinite(strip).mean() < .10:
                    raise RuntimeError(f"Invalid {band} strip {seg+1}")
                output[y0:y1, :] = strip
                output.flush()
                print(f"{band} strip {seg+1}/10, free RAM {free_gib():.2f} GiB", flush=True)
                while free_gib() < RESERVE_GIB:
                    print(f"Waiting within {band} after strip {seg+1}: RAM {free_gib():.2f} GiB; completed strips retained",flush=True);time.sleep(30)
            roi_path = ROOT / f"arrays/{band}.npy"
            same = None
            if roi_path.exists():
                roi = np.load(roi_path, mmap_mode="r")
                if roi.shape == (1200, 2000):
                    a = output[1250:2450, 1450:3450]
                    same = bool(np.array_equal(a, roi, equal_nan=True))
                    if not same:
                        delta = np.nanmax(np.abs(a-roi))
                        raise RuntimeError(f"Full disk ROI mismatch in {band}: max {delta}")
                    del a
                del roi
            del output, data, scene
            gc.collect()
        partial.replace(target)
        info["bands"][band] = {"seconds": time.perf_counter()-began,
                                "roi_exact_match": same, "free_ram_gib_after": free_gib(),"array_sha256":checksum(target)}
        publish()
        print("done", band, info["bands"][band], flush=True)
    publish(complete=True)
    print(json.dumps(info), flush=True)


if __name__ == "__main__":
    main()
