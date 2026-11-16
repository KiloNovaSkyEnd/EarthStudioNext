"""Bounded same-pixel crops compare JPEG qualities without rerunning the L1 recipe."""
import io
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image,ImageDraw

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ges_next.production.jpeg_layers import reconstruct

package=Path(sys.argv[1]).resolve();work=package/'work'
if not work.is_dir(): work=package/'scratch/work'
maps={name:np.load(work/(name+'.npy'),mmap_mode='r') for name in ['base','night','transmission','reference','support']}
folder=package/'verification/jpeg_comparison';folder.mkdir(parents=True,exist_ok=True)
records=[]
for label,(x,y) in {'clouds':(4700,3900),'night_detail':(3500,2700)}.items():
    crops={name:np.asarray(array[y:y+1536,x:x+1536]) for name,array in maps.items()}
    Image.fromarray(crops['reference']).save(folder/(label+'_reference.png'))
    board=Image.new('RGB',(1536,1064));draw=ImageDraw.Draw(board)
    for index,quality in enumerate([95,98,100]):
        encoded=[];total=0
        for name in ['base','night']:
            buffer=io.BytesIO();Image.fromarray(crops[name]).save(buffer,format='JPEG',quality=quality,subsampling=0)
            total+=len(buffer.getvalue());buffer.seek(0)
            with Image.open(buffer) as image: encoded.append(np.asarray(image).copy())
        pixels=reconstruct(*encoded,crops['transmission'])*255
        selected=crops['support']>0;difference=pixels[selected]-crops['reference'][selected]
        mse=float(np.mean(difference**2));mae=float(np.mean(abs(difference)))
        records.append(dict(crop=label,quality=quality,jpeg_bytes=total,mae=mae,psnr_db=float(10*np.log10(255**2/max(mse,1e-20)))))
        Image.fromarray(pixels.clip(0,255).astype(np.uint8)).save(folder/f'{label}_q{quality}.png')
        board.paste(Image.fromarray(pixels.clip(0,255).astype(np.uint8)).resize((512,512)),(index*512,32))
        delta=abs(pixels-crops['reference']).clip(0,31)*8
        board.paste(Image.fromarray(delta.clip(0,255).astype(np.uint8)).resize((512,512)),(index*512,552))
        draw.text((index*512+8,8),f'JPEG {quality} | MAE {mae:.3f} | error below x8',fill='white')
    board.save(folder/(label+'_comparison.png'))
(folder/'quality_crops.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
print(json.dumps(records,indent=2))
