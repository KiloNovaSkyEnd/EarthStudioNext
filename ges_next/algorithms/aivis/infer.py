"""Research-only H9 native full-disk AI tiling with fixed grid and RAM/VRAM guards.

Requires extract_full_disk_streaming.py outputs. This is a nighttime appearance
study, not a daytime truecolor blend or production integration.
"""

import ctypes
import os
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np
from pyorbital.orbital import get_observer_look
from pyproj import CRS, Transformer

ROOT = Path(__file__).resolve().parent
ASSET_ROOT = ROOT
BANDS = ("B08", "B09", "B10", "B11", "B13", "B15", "B16")
WEIGHT = ROOT / "aivis_setup/weights/aivis_1_0.safetensors"
EXPECTED = "e8a2e454fd86b81a1ab74087dc18fcf0f2019a9fa6321870f30b2c7f18de90e8"
GRID_SIZE = 5500
TILE_SIZE = 500
STARTS = [0, 375, 750, 1125, 1500, 1875, 2250, 2625, 3000, 3375, 3750, 4125, 4500, 4875, 5000]
WHEN = datetime(2026, 10, 20, 15, 20, tzinfo=timezone.utc)


def free_ram_gib():
    class S(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "free", "pt", "pf", "vt", "vf", "extra")]
    s = S()
    s.length = ctypes.sizeof(s)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.free/2**30


def clip(x):
    return np.clip(x, 0, 1)


def axis_weights(index):
    w = np.ones(TILE_SIZE, np.float32)
    if index:
        overlap = STARTS[index-1]+TILE_SIZE-STARTS[index]
        t = (np.arange(overlap, dtype=np.float32)+.5)/overlap
        w[:overlap] = np.sin(t*np.pi/2)**2
    if index+1 < len(STARTS):
        overlap = STARTS[index]+TILE_SIZE-STARTS[index+1]
        t = (np.arange(overlap, dtype=np.float32)+.5)/overlap
        w[-overlap:] = np.cos(t*np.pi/2)**2
    return w


def model_input(x, y, band_arrays, basemap, transformer):
    celsius = {}
    valid = np.ones((TILE_SIZE, TILE_SIZE), bool)
    for name in BANDS:
        block = np.asarray(band_arrays[name][y:y+TILE_SIZE, x:x+TILE_SIZE], np.float32)
        valid &= np.isfinite(block)
        celsius[name] = np.nan_to_num(block, nan=273.15, posinf=273.15, neginf=273.15)-273.15
    if not valid.any():
        return None, valid
    xx = -5_499_999.901174725+(np.arange(x, x+TILE_SIZE)+.5)*2000
    yy = 5_499_999.901174723-(np.arange(y, y+TILE_SIZE)+.5)*2000
    gx, gy = np.meshgrid(xx, yy)
    lon, lat = transformer.transform(gx, gy)
    valid &= np.isfinite(lon)&np.isfinite(lat)
    lon, lat = np.where(valid, lon, 0), np.where(valid, lat, 0)
    sat_az, sat_el = get_observer_look(140.7, 0, 35785.863, WHEN, lon, lat, 0)
    b = celsius
    channels = [
        1-clip((b["B13"]+103)/148),
        1-clip((b["B13"]-b["B15"]+3)/25),
        np.full_like(b["B13"], (-70+180)/360),
        1-clip((b["B13"]-b["B10"]+12)/74),
        1-clip((b["B11"]-b["B15"]+12)/34),
        1-clip((b["B13"]-b["B16"]+3)/44),
        1-clip((b["B13"]-b["B08"]+11)/91),
        1-clip((b["B13"]-b["B09"]+10)/80),
        np.full_like(b["B13"], 1-30/90),
        clip(sat_az/360),
        clip((90-sat_el)/90),
        np.asarray(basemap[y:y+TILE_SIZE, x:x+TILE_SIZE], np.float32)/255,
    ]
    arr = np.stack([np.uint8(clip(channel)*255) for channel in channels])
    arr[:, ~valid] = 0
    return arr, valid


def main():
    if hasattr(ctypes, "windll"):
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    if os.environ.get('EARTHSTUDIO_NIGHT_DEMAND') == '1':
        from .demand import required_native
        if not required_native(ROOT, os.environ['EARTHSTUDIO_NIGHT_MODE']).any():
            # Unused finite placeholders keep the existing display/quality path;
            # no cloud information is inferred and no model/GPU is initialized.
            source = np.load(ROOT/'full_disk_arrays/B13.npy', mmap_mode='r')
            if source.shape != (GRID_SIZE,GRID_SIZE):
                raise ValueError('Unexpected native source grid')
            empty = np.zeros(source.shape,np.float32)
            empty[~np.isfinite(source)] = np.nan
            np.save(ROOT/'full_disk_ai_tiled_gray.npy',empty)
            source._mmap.close()
            proof = dict(data_utc=WHEN.isoformat(),native_shape=[GRID_SIZE,GRID_SIZE],
                         demand_limited=True,tiles_selected=0,tiles_inferred=0,
                         model_loaded=False,gpu_used=False,
                         reason='Actual supported compositor night weight is zero; no AI appearance contributes')
            (ROOT/'full_disk_ai_tiled_gpu.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
            return
    while free_ram_gib() < 8:
        print(f"Waiting for AI RAM: available {free_ram_gib():.2f} GiB <8",flush=True);time.sleep(30)
    import torch
    from safetensors.torch import load_file
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    free_vram, _ = torch.cuda.mem_get_info()
    while free_vram < 4*1024**3:
        print(f"Waiting for GPU reserve: {free_vram/2**30:.2f} GiB free <4",flush=True);time.sleep(30)
        free_vram,_=torch.cuda.mem_get_info()
    if hashlib.sha256(WEIGHT.read_bytes()).hexdigest() != EXPECTED:
        raise RuntimeError("Model checksum mismatch")
    band_arrays = {name: np.load(ROOT / f"full_disk_arrays/{name}.npy", mmap_mode="r") for name in BANDS}
    if any(arr.shape != (GRID_SIZE, GRID_SIZE) for arr in band_arrays.values()):
        raise RuntimeError("Unexpected band shape")
    with np.load(ASSET_ROOT / "aivis_setup/author/himawari8.npz") as source:
        basemap = np.asarray(source["arr"])
    if basemap.shape != (GRID_SIZE, GRID_SIZE):
        raise RuntimeError(f"Unexpected basemap shape: {basemap.shape}")
    geos = CRS.from_proj4("+proj=geos +lon_0=140.7 +h=35785863 +a=6378137 +rf=298.257024882273 +units=m +no_defs")
    transformer = Transformer.from_crs(geos, CRS.from_epsg(4326), always_xy=True)
    spec = importlib.util.spec_from_file_location("author_pix2pix", ASSET_ROOT / "aivis_setup/author/pix2pix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.GeneratorUNet().eval()
    model.load_state_dict(load_file(str(WEIGHT), device="cpu"), strict=True)
    model = model.to("cuda")
    torch.set_num_threads(1)
    torch.backends.cudnn.benchmark = False
    demand = None
    selected_coordinates = None
    if os.environ.get('EARTHSTUDIO_NIGHT_DEMAND') == '1':
        from .demand import required_native, tile_coordinates
        demand = required_native(ROOT, os.environ['EARTHSTUDIO_NIGHT_MODE'])
        selected_coordinates = tile_coordinates(demand, STARTS, TILE_SIZE)
    selected_set = set(selected_coordinates) if selected_coordinates is not None else None
    sums = np.zeros((GRID_SIZE, GRID_SIZE), np.float32)
    weights = np.zeros_like(sums)
    model_times = []
    prep_times = []
    skipped = 0
    core_mismatch = None
    began = time.perf_counter()
    with torch.inference_mode():
        for j, y in enumerate(STARTS):
            for i, x in enumerate(STARTS):
                if selected_set is not None and (x,y) not in selected_set:
                    continue
                if free_ram_gib() < 5.5:
                    # Keep completed tiles and their exact accumulation order while waiting.
                    # No thresholds, model inputs or precision are changed.
                    torch.cuda.empty_cache()
                    while free_ram_gib() < 8:
                        print(f"Waiting before tile {i},{j}: RAM reserve {free_ram_gib():.2f} GiB; completed tiles retained",flush=True)
                        time.sleep(30)
                free_vram, _ = torch.cuda.mem_get_info()
                while free_vram < 2.5*1024**3:
                    print(f"Waiting before tile {i},{j}: VRAM reserve {free_vram/2**30:.2f} GiB; completed tiles retained",flush=True)
                    torch.cuda.empty_cache();time.sleep(30);free_vram,_=torch.cuda.mem_get_info()
                t0 = time.perf_counter()
                raw, valid = model_input(x, y, band_arrays, basemap, transformer)
                prep_times.append(time.perf_counter()-t0)
                if raw is None:
                    skipped += 1
                    continue
                if (x, y) == (2250, 1500):
                    # A separate direct-origin core comparison is performed below.
                    pass
                tensor = np.ones((12, 512, 512), np.float32)
                tensor[:, 6:-6, 6:-6] = 2*(raw.astype(np.float32)/255)-1
                t0 = time.perf_counter()
                prediction = model(torch.from_numpy(tensor).unsqueeze(0).to("cuda"))
                torch.cuda.synchronize()
                model_times.append(time.perf_counter()-t0)
                gray = (prediction[0, 0, 6:-6, 6:-6].float().cpu().numpy()+1)/2
                if not np.isfinite(gray).all():
                    raise RuntimeError(f"Invalid tile output at {x},{y}")
                win = axis_weights(i)[None, :]*axis_weights(j)[:, None]
                sums[y:y+TILE_SIZE, x:x+TILE_SIZE] += np.clip(gray, 0, 1)*win
                weights[y:y+TILE_SIZE, x:x+TILE_SIZE] += win
            print(f"row {j+1}/{len(STARTS)}, valid tiles {len(model_times)}, skipped {skipped}, free RAM {free_ram_gib():.2f} GiB", flush=True)
    mask = np.isfinite(band_arrays["B13"])
    if np.any(weights[mask if demand is None else (mask & demand)] < .999):
        raise RuntimeError("Valid disk has incomplete overlap coverage")
    ai = np.zeros_like(sums)
    np.divide(sums, weights, out=ai, where=weights>0)
    ai[~mask] = np.nan
    np.save(ROOT / "full_disk_ai_tiled_gray.npy", ai)
    # Validate exact quantized inputs on the old core, independent of tile grid.
    prior_path = ROOT / "ai_roi_input_u8.npy"
    if prior_path.exists():
        core, core_valid = model_input(2050, 1580, band_arrays, basemap, transformer)
        prior = np.load(prior_path, mmap_mode="r")[:, 330:830, 600:1100]
        core_mismatch = int(np.count_nonzero(core != prior))
        if core_mismatch:
            raise RuntimeError(f"Full disk input differs from exact ROI input: {core_mismatch}")
    result = {"data_utc": WHEN.isoformat(), "native_shape": [5500, 5500],
              "execution_revision": "night-demand-v1",
              "demand_limited": demand is not None,
              "tiles_selected": len(selected_coordinates) if selected_coordinates is not None else len(STARTS)**2,
              "tiles_skipped_not_required": len(STARTS)**2-len(selected_coordinates) if selected_coordinates is not None else 0,
              "tiles_total": len(STARTS)**2, "tiles_inferred": len(model_times), "tiles_skipped_outside_disk": skipped,
              "fixed_virtual_sza": 30, "fixed_virtual_azimuth": -70,
              "old_core_quantized_input_mismatch_values": core_mismatch,
              "model_seconds_sum": float(sum(model_times)), "prep_seconds_sum": float(sum(prep_times)),
              "loaded_process_seconds": float(time.perf_counter()-began),
              "gpu_name": torch.cuda.get_device_name(0), "torch": torch.__version__,
              "scope": "nighttime-native full disk research; not 11K daytime blend, no full animation"}
    (ROOT / "full_disk_ai_tiled_gpu.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
