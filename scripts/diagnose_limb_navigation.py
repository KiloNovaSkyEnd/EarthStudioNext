"""Compare authentic H8 polar navigation against accepted v8 KD-tree output."""
from pathlib import Path
import json
import numpy as np
from PIL import Image,ImageDraw
from ges.download import read_manifest
from ges.render import create_satpy_scene
from ges.geosampling import sample_native,native_indices

ROOT=Path(__file__).resolve().parents[1]


def main():
    source=ROOT/'data/raw/himawari8_20201029T164000Z/scene.json'
    meta=read_manifest(source);scene=create_satpy_scene(meta['local_files'],meta['satellite'])
    scene.load(['B13']);band=scene['B13'];area=band.attrs['area']
    native=np.ma.filled(band.compute().values,np.nan)
    # Use exact accepted 8K pixel centres, northern polar band only.
    width=8192;rows=np.arange(0,683);lon=-180+(np.arange(width)+.5)*360/width
    lat=90-(rows+.5)*360/width
    new=sample_native(area,[native],lon[None,:],lat[:,None])[0]
    ix,iy,nav=native_indices(area,lon[None,:],lat[:,None])
    valid=np.isfinite(new)&(new>=100)&(new<=350)
    oldpath=ROOT/'data/processed/validation_v8/himawari8_1640/ahi_evidence_night_coverage.png'
    old=np.asarray(Image.open(oldpath))[:683]>0
    report={'source_manifest':str(source.relative_to(ROOT)),'nominal_utc':'2020-10-29T16:40:00Z',
        'region':'exact 8K global centres, northernmost 683 rows (~60..90N)',
        'old_coverage_pixels':int(old.sum()),'inverse_native_pixels':int(valid.sum()),
        'inverse_only':int((valid&~old).sum()),'old_only':int((old&~valid).sum()),
        'each_new_pixel_matches_float32_native_sample':bool(np.array_equal(new[valid],native[iy[valid],ix[valid]].astype(np.float32))),
        'max_float32_conversion_error_kelvin':float(np.max(np.abs(new[valid]-native[iy[valid],ix[valid]]))),
        'native_mapping_not_gap_filling':True,'is_independent_truth':False}
    out=ROOT/'data/processed/limb_navigation_audit';out.mkdir(parents=True,exist_ok=True)
    (out/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    panels=[]
    panels.append(np.repeat(old[...,None]*255,3,axis=2).astype(np.uint8))
    panels.append(np.repeat(valid[...,None]*255,3,axis=2).astype(np.uint8))
    delta=np.zeros(old.shape+(3,),dtype=np.uint8);delta[valid&~old]=(0,200,100);delta[old&~valid]=(255,80,50)
    panels.append(delta)
    sheet=Image.new('RGB',(2048,600),(12,15,22));draw=ImageDraw.Draw(sheet)
    for i,(a,label) in enumerate(zip(panels,['V8 KD-tree coverage','Inverse native footprint coverage','Green: inverse-only / red: KD-only'])):
        sheet.paste(Image.fromarray(a).resize((2048,171),Image.Resampling.NEAREST),(0,i*200+29))
        draw.text((12,i*200+8),label+' / Himawari-8 2020-10-29 16:40 UTC',fill='white')
    sheet.save(out/'polar_coverage_comparison.png');print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
