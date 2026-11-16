"""Read-only reference inspection; decode local video, fingerprint PNGs and export sheets."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sheet(items, out, cols=4):
    result = Image.new('RGB', (640*cols, 388*math.ceil(len(items)/cols)), '#09111c')
    draw = ImageDraw.Draw(result)
    for i, (path, label) in enumerate(items):
        x, y = i % cols*640, i//cols*388
        with Image.open(path) as im:
            im = im.convert('RGB'); im.thumbnail((640,360))
            result.paste(im, (x+(640-im.width)//2,y+28))
        draw.text((x+10,y+8),label,fill='white')
    result.save(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-dir',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=False)
    records=[]; previews=[]
    for i,path in enumerate(sorted(args.reference_dir.rglob('*.png'))):
        with Image.open(path) as im:
            im.load(); pixels=np.asarray(im.convert('RGB'))
            record={'file':str(path.resolve()),'bytes':path.stat().st_size,
                    'sha256':digest(path),'pixel_sha256':hashlib.sha256(pixels.tobytes()).hexdigest(),
                    'dimensions':list(im.size)}
            preview=args.out/f'still_{i+1:02d}.jpg'
            im.convert('RGB').resize((1280,720)).save(preview,quality=94)
            # Timestamp/text region at native resolution for human reading.
            im.crop((0,0,im.width,min(400,im.height))).save(args.out/f'still_{i+1:02d}_header.png')
        records.append(record); previews.append((preview,f'still {i+1:02d} | {path.stem.split("_")[-1]}'))
    for i in range(0,len(previews),12):
        sheet(previews[i:i+12],args.out/f'stills_sheet_{i//12+1}.jpg')
    videos=[]
    for index,path in enumerate(sorted(args.reference_dir.rglob('*.mp4'))):
        dest=args.out/f'video_{index+1:02d}';dest.mkdir()
        reader=imageio_ffmpeg.read_frames(str(path),pix_fmt='rgb24')
        meta=next(reader);reader.close()
        command=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-nostdin','-n','-i',str(path),
                 '-map','0:v:0','-vf','fps=1/4,scale=640:-2','-q:v','3',str(dest/'sample_%04d.jpg')]
        run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace')
        (dest/'decode.log').write_text(run.stderr,encoding='utf-8')
        if run.returncode: raise RuntimeError(run.stderr[-2000:])
        samples=sorted(dest.glob('sample_*.jpg'))
        for i in range(0,len(samples),12):
            # fps filter samples nearest the centres of 4-second bins.
            sheet([(p,f'video sample {j+1:03d} | approx {2+4*j}s') for j,p in enumerate(samples) if i<=j<i+12],
                  dest/f'sheet_{i//12+1:02d}.jpg')
        videos.append({'file':str(path.resolve()),'bytes':path.stat().st_size,'sha256':digest(path),
                       'metadata':meta,'sample_count':len(samples),'sample_interval_s':4,
                       'sample_time_note':'fps filter bin centre approx2+4*i seconds; no source weather UTC inferred',
                       'full_video_decoded':True,'ffmpeg_exit_code':run.returncode})
    report={'stills':records,'videos':videos,'unique_still_pixels':len({r['pixel_sha256'] for r in records}),
            'reference_files_unchanged':all(digest(Path(r['file']))==r['sha256'] for r in records+videos)}
    assert report['reference_files_unchanged']
    (args.out/'media_inventory.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('READ',len(records),'PNG,',report['unique_still_pixels'],'unique;',len(videos),'videos',flush=True)
    print(json.dumps(videos,indent=2,ensure_ascii=True),flush=True)


if __name__=='__main__': main()
