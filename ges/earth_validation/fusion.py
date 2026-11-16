"""Geographic overlap feathering of finished stock pixels, in linear light.

No spectral correction, fake surface fill, cloud classification or time synthesis.
Only two nearest observed views participate in a narrow overlap transition.
"""
import numpy as np


def linear(rgb, xp=np):
    value=rgb.astype(np.float32)/255
    return xp.where(value<=.04045,value/12.92,((value+.055)/1.055)**2.4)


def srgb(values, xp=np):
    value=xp.clip(values,0,1)
    return xp.rint(255*xp.where(value<=.0031308,12.92*value,1.055*value**(1/2.4)-.055)).astype(np.uint8)


def fuse(sources,longitude,latitude,feather_degrees=2,latitude_limit=70,backend='cpu'):
    if backend=='cuda':
        from .gpu import fuse_cuda
        return fuse_cuda(sources,longitude,latitude,feather_degrees,latitude_limit)
    return _fuse(sources,longitude,latitude,feather_degrees,latitude_limit,np)


def _fuse(sources,longitude,latitude,feather_degrees,latitude_limit,np):
    shape=longitude.shape
    best=np.full(shape,np.inf); second=np.full(shape,np.inf)
    rgb=np.zeros(shape+(4,),np.uint8); alternate=np.zeros_like(rgb)
    owner=np.zeros(shape,np.uint8)
    for number,(pixels,lon0) in enumerate(sources,1):
        distance=np.arccos(np.clip(np.cos(np.deg2rad(latitude))*np.cos(np.deg2rad(longitude-lon0)),-1,1))
        valid=(pixels[...,3]>0)&(np.abs(latitude)<latitude_limit)
        choose=valid&(distance<best)
        alternate[choose]=rgb[choose]; second[choose]=best[choose]
        use_second=valid&~choose&(distance<second)
        alternate[use_second]=pixels[use_second]; second[use_second]=distance[use_second]
        rgb[choose]=pixels[choose]; best[choose]=distance[choose]; owner[choose]=number
    weight=np.zeros(shape,np.float32)
    valid=np.isfinite(second)&np.isfinite(best)
    if feather_degrees>0:
        weight[valid]=.5*np.clip(1-(second[valid]-best[valid])/np.deg2rad(feather_degrees),0,1)
    blend=weight>0
    rgb[blend,:3]=srgb(linear(rgb[blend,:3],np)*(1-weight[blend,None])+linear(alternate[blend,:3],np)*weight[blend,None],np)
    return rgb,owner,weight
