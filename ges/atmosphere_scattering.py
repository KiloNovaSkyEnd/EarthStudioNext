"""Optional GPU single-scattering research renderer and fixed test cameras.

No cloud generation, polar filling, source recoloring, or weather interpolation.
Standard atmosphere parameters are not measured at the source acquisition UTC.
"""
from pathlib import Path
from functools import wraps
import math
import numpy as np

VERTEX='''#version 330
in vec2 position;
void main(){gl_Position=vec4(position,0.,1.);}
'''


def _current_context(method):
    @wraps(method)
    def active(self,*args,**kwargs):
        with self.ctx:
            return method(self,*args,**kwargs)
    return active


def sphere_roots(position,direction,radius):
    p=np.asarray(position,float);d=np.asarray(direction,float)
    b=np.sum(p*d,axis=-1);disc=b*b-np.sum(p*p,axis=-1)+radius*radius
    s=np.sqrt(np.maximum(disc,0));return np.stack([np.where(disc>=0,-b-s,np.inf),np.where(disc>=0,-b+s,-np.inf)],axis=-1)


def solar_visibility(position,sun):
    p=np.asarray(position,float);r=np.linalg.norm(p,axis=-1);mu=np.sum(p*np.asarray(sun),axis=-1)/r
    horizon=-np.sqrt(np.maximum(0,1-6371**2/r**2));t=np.clip((mu-horizon+.004675)/.00935,0,1)
    return t**3*(t*(6*t-15)+10)


def geographic(lon,lat,radius):
    lo,la=np.deg2rad([lon,lat]);return radius*np.array([np.cos(la)*np.cos(lo),np.cos(la)*np.sin(lo),np.sin(la)])


def camera_basis(position,target,up):
    forward=np.asarray(target,float)-position;forward/=np.linalg.norm(forward)
    right=np.cross(forward,up);size=np.linalg.norm(right)
    if size<1e-8:raise ValueError('Camera up parallel to look direction')
    right/=size;return right,np.cross(right,forward),forward


def orbit_camera(lon,lat,altitude_km,fov=45,heading=-1):
    if not np.isfinite(altitude_km) or altitude_km<.1:raise ValueError('Camera must be above ground')
    position=geographic(lon,lat,6371+altitude_km)
    tangent=math.degrees(math.acos(6371/(6371+altitude_km)))
    target=geographic(lon+heading*tangent*.85,lat,6371)
    return {'position':position,'target':target,'up':position/np.linalg.norm(position),'fov':fov}


class ScatteringRenderer:
    def __init__(self,images,width=960,height=540,supersample=1,cloud_layer=None,ocean_mask=None):
        import moderngl
        self.ctx=moderngl.create_standalone_context(require=330);self.width=width;self.height=height
        self.render_width=round(width*supersample);self.render_height=round(height*supersample)
        fragment=(Path(__file__).parent/'shaders/atmosphere_scattering.frag').read_text()
        self.program=self.ctx.program(vertex_shader=VERTEX,fragment_shader=fragment)
        self.buffer=self.ctx.buffer(np.array([[-1,-1],[3,-1],[-1,3]],np.float32).tobytes())
        self.vao=self.ctx.vertex_array(self.program,[(self.buffer,'2f','position')])
        self.target=self.ctx.texture((self.render_width,self.render_height),4,dtype='f4');self.fbo=self.ctx.framebuffer([self.target])
        self.textures=[]
        for index,(name,values) in enumerate(zip(['current_surface','frozen_day','frozen_night'],images)):
            a=np.ascontiguousarray(values[...,:3],dtype=np.uint8)
            tex=self.ctx.texture((a.shape[1],a.shape[0]),3,a.tobytes(),alignment=1)
            tex.repeat_x=True;tex.repeat_y=False;tex.build_mipmaps()
            tex.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR);tex.use(index)
            tex.anisotropy=16.
            self.textures.append(tex);self.program[name].value=index
        self.program['resolution'].value=(self.render_width,self.render_height)
        self.has_cloud_layer = cloud_layer is not None
        cloud, heights = cloud_layer if self.has_cloud_layer else (np.zeros((2,4,4),np.uint8), np.zeros((2,4),np.float32))
        cloud = np.asarray(cloud)
        heights = np.asarray(heights)
        if (cloud.ndim != 3 or cloud.shape[2] != 4 or cloud.shape[1] != 2*cloud.shape[0]
                or heights.ndim != 2 or heights.shape[1] != 2*heights.shape[0]):
            raise ValueError('2:1 independent cloud RGBA and height grids required')
        supported=np.isfinite(heights)&(heights>0)&(heights<=20)
        height_texture=np.dstack([np.where(supported,heights,0),supported.astype(np.float32)])
        for index, (name, a, components, dtype) in enumerate([
            ('independent_cloud',np.ascontiguousarray(cloud,dtype=np.uint8),4,'f1'),
            ('cloud_height',np.ascontiguousarray(height_texture,dtype=np.float32),2,'f4')],3):
            tex=self.ctx.texture((a.shape[1],a.shape[0]),components,a.tobytes(),alignment=1,dtype=dtype)
            tex.repeat_x=True;tex.repeat_y=False
            # Premultiplied cloud RGB avoids black fringes in transparent mipmaps.
            if name=='independent_cloud':
                a=a.copy();a[...,:3]=np.rint(a[...,:3].astype(np.float32)*a[...,3:4]/255).astype(np.uint8)
                tex.write(a.tobytes());tex.build_mipmaps();tex.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR);tex.anisotropy=16.
            else:tex.filter=(moderngl.LINEAR,moderngl.LINEAR)
            tex.use(index);self.textures.append(tex);self.program[name].value=index
        self.has_ocean_mask=ocean_mask is not None
        mask=np.zeros((2,4),np.uint8) if ocean_mask is None else np.asarray(ocean_mask)
        if mask.ndim!=2 or mask.shape[1]!=2*mask.shape[0]:
            raise ValueError('2:1 geographic ocean mask required')
        mask=np.ascontiguousarray(mask,dtype=np.uint8)
        tex=self.ctx.texture((mask.shape[1],mask.shape[0]),1,mask.tobytes(),alignment=1)
        tex.repeat_x=True;tex.repeat_y=False;tex.filter=(moderngl.LINEAR,moderngl.LINEAR)
        tex.use(5);self.textures.append(tex);self.program['ocean_mask'].value=5

    @property
    def device(self):return self.ctx.info['GL_RENDERER']

    @_current_context
    def render(self,camera,sun,enabled=True,airglow=False,dynamic=False,steps=64,sun_steps=12,exposure=3.,gain=1.,float_output=False,relief_strength=.35,night_depth_strength=0.,stable_cloud_sampling=True,ocean_material=False):
        if not np.isfinite(relief_strength) or not 0<=relief_strength<=.5:
            raise ValueError('Restrained relief strength must be in 0..0.5')
        self.program['separate_cloud_enabled'].value=self.has_cloud_layer
        self.program['relief_strength'].value=relief_strength
        if not np.isfinite(night_depth_strength) or not 0<=night_depth_strength<=1:
            raise ValueError('Night display depth strength must be in 0..1')
        self.program['night_depth_strength'].value=night_depth_strength
        if ocean_material and not self.has_ocean_mask:
            raise ValueError('Explicit geographic ocean mask required for ocean material')
        self.program['stable_cloud_sampling'].value=bool(stable_cloud_sampling)
        self.program['ocean_material_enabled'].value=bool(ocean_material)
        right,up,forward=camera_basis(np.asarray(camera['position']),camera['target'],camera['up'])
        values={'camera_position':camera['position'],'camera_right':right,'camera_up':up,'camera_forward':forward,'sun_direction':sun}
        for name,value in values.items():self.program[name].value=tuple(map(float,value))
        if not 8<=steps<=192 or not 4<=sun_steps<=32:raise ValueError('Integration sample count outside supported range')
        for name,value in {'tan_half_fov':math.tan(math.radians(camera['fov'])/2),'scattering_exposure':exposure,
            'airglow_gain':gain,'view_samples':steps,'sun_samples':sun_steps,'atmosphere_enabled':enabled,
            'airglow_enabled':airglow,'dynamic_surface':dynamic}.items():self.program[name].value=value
        # Texture-unit bindings are GL state, not owned by a renderer instance.
        for unit,texture in enumerate(self.textures):texture.use(unit)
        self.fbo.use();self.ctx.viewport=(0,0,self.render_width,self.render_height);self.vao.render(vertices=3)
        pixels=np.frombuffer(self.fbo.read(components=4,dtype='f4'),np.float32).reshape(self.render_height,self.render_width,4)[::-1].copy()
        if not np.isfinite(pixels).all():raise ValueError('Non-finite atmosphere render')
        if float_output:
            if self.render_width!=self.width:
                from PIL import Image
                pixels=np.stack([np.asarray(Image.fromarray(pixels[...,i]).resize((self.width,self.height),Image.Resampling.LANCZOS)) for i in range(4)],axis=-1)
            return pixels
        result=np.rint(np.clip(pixels[...,:3],0,1)*255).astype(np.uint8)
        if self.render_width!=self.width:
            from PIL import Image
            result=np.asarray(Image.fromarray(result).resize((self.width,self.height),Image.Resampling.LANCZOS)).copy()
        return result

    def close(self):
        with self.ctx:
            for texture in self.textures:texture.release()
            self.vao.release();self.buffer.release();self.fbo.release();self.target.release();self.program.release()
        self.ctx.release()
