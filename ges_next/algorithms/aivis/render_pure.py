"""Render the cached whole-disk AI-VIS output without IR-conditioned V9 mixing."""
import ctypes
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
from .limb import correct_native_limb

ROOT=Path(__file__).resolve().parent
UTC='2026-10-20T15:20:00Z'
PALETTE=np.array([[5,8,14],[46,48,54],[140,144,151],[231,231,231]],np.float32)
KNOTS=[0,.18,.5,1]

def free_ram_gib():
    class S(ctypes.Structure):
        _fields_=[("length",ctypes.c_ulong),("load",ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ("total","free","pt","pf","vt","vf","extra")]
    s=S();s.length=ctypes.sizeof(s)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.free/2**30

def colorize(gray):
    rgb=np.stack([np.interp(gray,KNOTS,PALETTE[:,i]) for i in range(3)],axis=-1)
    return Image.fromarray(np.uint8(np.rint(np.clip(rgb,0,255))),"RGB")

def wait_ram(minimum):
    while free_ram_gib() < minimum:
        print(f"Waiting for RAM reserve {minimum} GiB; free={free_ram_gib():.2f}", flush=True)
        time.sleep(10)


def main():
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),0x4000)
    wait_ram(8)
    ai=np.load(ROOT/"full_disk_ai_tiled_gray.npy",mmap_mode="r")
    ir=np.load(ROOT/"full_disk_arrays/B13.npy",mmap_mode="r")
    if ai.shape!=(5500,5500) or ir.shape!=ai.shape:
        raise RuntimeError("Unexpected whole-disk source shape")
    output=ROOT/"full_disk_pure_ai_vis_11000.jpg"
    preview=ROOT/"full_disk_pure_ai_vis_preview.png"
    if output.exists() or preview.exists():
        raise FileExistsError("Pure AI outputs already exist; preserve them")
    began=time.perf_counter()
    corrected, limb_stats=correct_native_limb(ai,ir)
    im=Image.new("RGB",(5500,5500),(0,0,0))
    for y in range(0,5500,250):
        block=corrected[y:y+250]
        im.paste(colorize(block),(0,y))
        wait_ram(6)
    im.resize((1100,1100),Image.Resampling.BOX).save(preview)
    full=im.resize((11000,11000),Image.Resampling.BILINEAR)
    full.save(output,quality=95,subsampling=0)
    with Image.open(output) as check:
        if check.size!=(11000,11000):raise RuntimeError("11K output verification failed")
    info={"utc":UTC,"output":str(output),"shape":[11000,11000],
          "output_bytes":output.stat().st_size,"seconds_colorize_resize_encode":time.perf_counter()-began,
          "model_source":"cached full_disk_ai_tiled_gray.npy, inferred from seven H9 IR bands plus static basemap and viewing geometry",
          "display":"fixed slightly cool grayscale palette; no B13-derived cloud brightness, low-cloud or warm-cloud corrections; no ground night-light composite",
          "native_information":"IR cloud information 2 km, AI estimates visible-like appearance; 11K is 2x resample, not new observation",
          "limb_correction":"inward-only estimate and footprint taper over five native IR pixels; interior unchanged",
          "limb_ring_stats":limb_stats,
          "scope":"single-night whole-disk appearance study, not validated sunrise/sunset sequence"}
    (ROOT/"full_disk_pure_ai_vis_11k.json").write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(info,ensure_ascii=False),flush=True)

if __name__=="__main__":main()
