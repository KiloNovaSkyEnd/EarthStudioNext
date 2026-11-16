"""Bounded real 2022-August OC-CCI water optics subset; not instantaneous weather."""
import hashlib
import argparse
import json
import math
from pathlib import Path

import requests
import numpy as np
import xarray as xr
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
BASE='https://comet.nefsc.noaa.gov/erddap/griddap/occci_V6_monthly_4km'
BANDS=[412,443,490,510,560,665]


def rgb_equivalent_probe(spectra,nobs):
    """Display-only three-sample proxy; leave every measured value untouched."""
    s=np.asarray(spectra);n=np.asarray(nobs)
    if s.ndim!=3 or s.shape[2]!=6 or s.shape[:2]!=n.shape:
        raise ValueError('Six ordered Rrs bands and matching observation-count grid required')
    selected=s[:,:,[5,4,1]]
    support=np.isfinite(selected).all(-1)&(selected>=0).all(-1)&(selected<=.1).all(-1)&np.isfinite(n)&(n>0)
    proxy=np.where(support[:,:,None],np.pi*selected,0).astype(np.float32)
    return proxy,support


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--retry-empty',action='store_true');args=ap.parse_args()
    raw=ROOT/'data/raw/reference/occci_202208_east_asia_v1';raw.mkdir(exist_ok=args.retry_empty)
    if args.retry_empty:
        if any(p.suffix in ['.nc','.part'] for p in raw.iterdir()):raise ValueError('Existing raw payload must not be overwritten')
        old=raw/'download_plan.json'
        if old.exists():
            with (raw/'initial_attempt_plan.json').open('xb') as f:f.write(old.read_bytes())
    out=ROOT/'data/processed/hinnamnor_ocean_research_v2';out.mkdir(exist_ok=True)
    variables=[f'Rrs_{b}{s}' for b in BANDS for s in ['', '_bias','_rmsd']]+['total_nobs_sum']
    constraint='[(2022-08-01T00:00:00Z)][(45):1:(15)][(112):1:(146)]'
    url=BASE+'.nc?'+','.join(v+constraint for v in variables)
    estimate=(math.ceil(30*24)+3)*(math.ceil(34*24)+3)*19*4+2_000_000
    plan=dict(url=url,variables=variables,period='2022-08 monthly composite, not 2022-08-31 instantaneous water state',
        estimated_maximum_bytes=estimate,hard_limit_bytes=60_000_000,
        bounding_box_wsen=[112,15,146,45],documentation=BASE+'.html',
        source='ESA Ocean Colour CCI v6, NOAA ERDDAP redistribution, not a NASA MODIS-only product')
    assert estimate<50_000_000
    (raw/'download_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    path=raw/'occci_v6_202208_east_asia.nc';part=path.with_suffix('.nc.part');total=0
    with requests.get(url,headers={'Accept-Encoding':'identity'},stream=True,timeout=(15,180)) as response:
        response.raise_for_status()
        length=response.headers.get('Content-Length')
        if length and int(length)>plan['hard_limit_bytes']:raise ValueError('Body exceeds preflight budget')
        with part.open('xb') as f:
            for chunk in response.iter_content(1024*1024):
                total+=len(chunk)
                if total>plan['hard_limit_bytes']:raise ValueError('Hard download limit exceeded; partial retained')
                f.write(chunk)
    with xr.open_dataset(part) as ds:
        assert ds.sizes['time']==1 and str(ds.time.values[0]).startswith('2022-08-01')
        assert ds.sizes['latitude']<=723 and ds.sizes['longitude']<=819
        assert all(ds[f'Rrs_{b}'].attrs.get('units')=='sr-1' for b in BANDS)
        lat=ds.latitude.values;lon=ds.longitude.values
        assert (np.diff(lat)<0).all() and (np.diff(lon)>0).all()
        spectra=np.stack([ds[f'Rrs_{b}'].isel(time=0).values for b in BANDS],-1).astype(np.float32)
        nobs=ds.total_nobs_sum.isel(time=0).values
        rmsd=np.stack([ds[f'Rrs_{b}_rmsd'].isel(time=0).values for b in BANDS],-1).astype(np.float32)
        bias=np.stack([ds[f'Rrs_{b}_bias'].isel(time=0).values for b in BANDS],-1).astype(np.float32)
        attrs={k:str(v) for k,v in ds.attrs.items()}
    part.rename(path)
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    plan.update(actual_bytes=total,sha256=digest,shape=list(spectra.shape),attributes=attrs)
    (raw/'download_verified.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    np.savez_compressed(out/'observed_rrs_202208.npz',wavelength_nm=BANDS,Rrs_sr_inverse=spectra,rmsd_sr_inverse=rmsd,bias_sr_inverse=bias,latitude=lat,longitude=lon,total_nobs=nobs)
    # Explicitly approximate 3-sample Lambertian RGB-equivalent probe. These
    # are NOT spectrally integrated sRGB or a retrieved BSDF. Keep raw Rrs above.
    proxy,support=rgb_equivalent_probe(spectra,nobs)
    rgba=np.dstack([proxy,support.astype(np.float32)]).astype(np.float32)
    np.save(out/'rrs_rgb_equivalent_probe.npy',rgba,allow_pickle=False)
    dx=float(np.median(np.diff(lon)));dy=float(-np.median(np.diff(lat)))
    meta=dict(extent_wsen=[float(lon[0]-dx/2),float(lat[-1]-dy/2),float(lon[-1]+dx/2),float(lat[0]+dy/2)],
        shape=list(rgba.shape),product='ESA OC-CCI v6 2022-Aug monthly Rrs, actual observations merged by provider',
        mapping='Probe only: linear RGB-equivalent = pi*[Rrs665,Rrs560,Rrs443]; no true-color/BRDF accuracy claim',
        support='Only these3 Rrs finite0..0.1sr^-1 and total_nobs>0; missing/negative retained in raw archive and refused in display probe; no gap fill',
        supported_pixels=int(support.sum()),support_fraction=float(support.mean()),
        raw_source_sha256=digest,raw_wavelengths_nm=BANDS,
        missing_fraction_by_band=[float((~np.isfinite(spectra[:,:,i])).mean()) for i in range(6)],
        finite_Rrs_p01_p50_p99={str(b):np.nanpercentile(spectra[:,:,i],[1,50,99]).tolist() for i,b in enumerate(BANDS)},
        limitations='4km monthly retrieval; biased/uncertain/coastal/adjacent-cloud effects possible; uncertainty fields archived, no invented fine texture')
    (out/'rrs_probe_metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    linear=np.maximum(proxy,0);display=np.where(linear<=.0031308,linear*12.92,1.055*linear**(1/2.4)-.055)
    Image.fromarray(np.dstack([np.rint(np.clip(display,0,1)*255).astype(np.uint8),support.astype(np.uint8)*255])).save(out/'real_rrs_rgb_equivalent_probe.png')
    print(json.dumps(dict(downloaded=total,source_shape=spectra.shape,support_fraction=meta['support_fraction'],extent=meta['extent_wsen'])),flush=True)


if __name__=='__main__':main()
