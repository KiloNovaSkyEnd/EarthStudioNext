"""Label real Blender renders, preserving the observations in the source PNG."""
from pathlib import Path
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]


def main():
    folder=ROOT/'data/processed/atmosphere_v1'
    sheet=Image.new('RGB',(3840,3*1136),(10,14,22));draw=ImageDraw.Draw(sheet)
    rows=[('day_horizon_off.png','day_horizon_on.png','DAY HORIZON'),
          ('night_horizon_off.png','night_horizon_on.png','NIGHT AIRGLOW'),
          ('toggle_off.png','both_on.png','GLOBAL TWILIGHT')]
    for row,(off,on,label) in enumerate(rows):
        for col,name in enumerate([off,on]):
            im=Image.open(folder/name).convert('RGB');sheet.paste(im,(col*1920,row*1136+56))
            draw.text((col*1920+20,row*1136+18),label+(' / EFFECTS OFF' if col==0 else ' / OPTIONAL EFFECTS ON - NOT MEASURED ATMOSPHERE'),fill='white')
    sheet.save(folder/'comparison.png');print(folder/'comparison.png')


if __name__=='__main__':main()
