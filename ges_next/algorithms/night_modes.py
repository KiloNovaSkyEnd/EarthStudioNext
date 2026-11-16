"""Versioned optional night recipes. Absence preserves the existing GeoColor contract."""
from dataclasses import dataclass
import hashlib,json

MODEL_SHA256='e8a2e454fd86b81a1ab74087dc18fcf0f2019a9fa6321870f30b2c7f18de90e8'
DAY_BANDS=('B01','B02','B03','B04','B07','B13')
IR_BANDS=('B07','B08','B09','B10','B11','B13','B15','B16')

@dataclass(frozen=True)
class NightRecipe:
    mode:str
    version:str
    bands:tuple
    weights_sha256:str|None=None
    night_chroma_scale:float=1.
    def identity(self):
        if self.mode=='geocolor':return None
        return dict(mode=self.mode,version=self.version,bands=list(self.bands),weights_sha256=self.weights_sha256,
            virtual_sza=30,virtual_azimuth=-70,night_chroma_scale=self.night_chroma_scale,
            landmask_sha256='13eadbe04ebd339deb8ec2e476afd4a2863961676e412e16230015fa57c43806',ir_grid=[5500,5500],output_grid=[11000,11000],interpretation='AI-inferred appearance from satellite IR, not measured VIS')

RECIPES={
    'geocolor':NightRecipe('geocolor','existing-satpy',DAY_BANDS),
    'ai-vis':NightRecipe('ai-vis','neutral-night-v1',tuple(sorted(set(DAY_BANDS+IR_BANDS))),MODEL_SHA256,.25),
    'ai-vis-ir':NightRecipe('ai-vis-ir','v9-neutral-night-v1',tuple(sorted(set(DAY_BANDS+IR_BANDS))),MODEL_SHA256,.25),
}

def recipe(profile):
    mode=profile.get('NightMode') or 'geocolor'
    if mode not in RECIPES:raise ValueError('Unknown night recipe: '+str(mode))
    return RECIPES[mode]

def signature(profile):
    value=recipe(profile).identity()
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest() if value else None

def reduce_night_chroma(rgb,scale=.25):
    import numpy as np
    if not 0<=scale<=1:raise ValueError('Chroma scale must be within 0..1')
    rgb=np.asarray(rgb,dtype=np.float32)
    luminance=np.sum(rgb*np.array([.2126,.7152,.0722],np.float32),axis=-1,keepdims=True)
    return luminance+scale*(rgb-luminance)

def neutral_ground_background(rgb):
    import numpy as np
    rgb=np.asarray(rgb,dtype=np.float32)
    cool=np.clip((rgb[...,2:3]-rgb[...,0:1])*30,0,1)
    luminance=np.sum(rgb*np.array([.2126,.7152,.0722],np.float32),axis=-1,keepdims=True)
    return rgb+cool*.75*(luminance-rgb)

def compose(day,night,solar,cloud,support,mode):
    import numpy as np
    if mode not in ('ai-vis','ai-vis-ir'):raise ValueError('Optional night compositor only')
    amount=1-solar
    if mode=='ai-vis-ir':amount=amount*cloud
    result=np.clip(solar[...,None]*day+amount[...,None]*reduce_night_chroma(night),0,1)
    return np.where(support[...,None],result,0)
