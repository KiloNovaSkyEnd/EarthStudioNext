"""Native-projection AHI cloud-column volume preview, not a 3D retrieval.

Top heights are measured retrievals. Cloud base, extinction and vertical density
are display assumptions. No noise, painted clouds, invented timestamps or glint.
"""
from pathlib import Path
import math
import numpy as np
from .atmosphere_scattering import VERTEX,camera_basis


def native_project(longitude,latitude,projection):
    """Independent CPU equivalent for verifying the GLSL sweep-y AHI mapping."""
    lo=np.deg2rad(np.asarray(longitude)-projection['lon_0']);la=np.deg2rad(latitude)
    a,b,h=projection['a'],projection['b'],projection['h'];e2=1-b*b/(a*a)
    q=a/np.sqrt(1-e2*np.sin(la)**2)
    x=q*np.cos(la)*np.cos(lo);y=q*np.cos(la)*np.sin(lo);z=q*(1-e2)*np.sin(la)
    dx=a+h-x;valid=dx*x-y*y-z*z/(1-e2)>=0
    return np.where(valid,h*np.arctan2(y,dx),np.nan),np.where(valid,h*np.arctan2(z,np.hypot(dx,y)),np.nan)


class NativeCloudRenderer:
    def _fragment_shader(self):
        return (Path(__file__).parent/'shaders/goni_film.frag').read_text()

    def __init__(self,day,night,width=1280,height=720,supersample=1.25,opacity_gamma=1.,geometry_bridge_pixels=0,ocean_mask=None):
        import moderngl
        self.ctx=moderngl.create_standalone_context(require=330);self.width=width;self.height=height
        if not np.isfinite(opacity_gamma) or not .8<=opacity_gamma<=1.5 or not isinstance(geometry_bridge_pixels,int) or not 0<=geometry_bridge_pixels<=3:
            raise ValueError('Bounded display opacity/geometry profile required')
        self.opacity_gamma=opacity_gamma;self.geometry_bridge_pixels=geometry_bridge_pixels
        self.w=round(width*supersample);self.h=round(height*supersample)
        self.program=self.ctx.program(vertex_shader=VERTEX,fragment_shader=self._fragment_shader())
        self.buffer=self.ctx.buffer(np.array([[-1,-1],[3,-1],[-1,3]],np.float32).tobytes())
        self.vao=self.ctx.vertex_array(self.program,[(self.buffer,'2f','position')]);self.textures=[]
        for i,values in enumerate([day,night]):
            a=np.ascontiguousarray(values[...,:3],np.uint8)
            tex=self.ctx.texture((a.shape[1],a.shape[0]),3,a.tobytes(),alignment=1)
            tex.repeat_x=True;tex.repeat_y=False;tex.build_mipmaps();tex.anisotropy=16
            tex.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR);tex.use(i);self.textures.append(tex)
        for name,slot in [('ground_day',0),('ground_night',1),('cloud_rgba',2),('cloud_top',3)]:self.program[name].value=slot
        water=np.zeros((2,4),np.uint8) if ocean_mask is None else np.asarray(ocean_mask)
        if water.ndim!=2 or water.shape[1]!=2*water.shape[0]:raise ValueError('2:1 static geographic ocean mask required')
        self.water=self.ctx.texture((water.shape[1],water.shape[0]),1,np.ascontiguousarray(water,np.uint8).tobytes(),alignment=1)
        self.water.repeat_x=True;self.water.repeat_y=False;self.water.build_mipmaps()
        self.program['ocean_mask'].value=4
        # Optional static regional night reference; global/default path stays intact.
        self.night_detail=self.ctx.texture((1,1),3,b'\x00\x00\x00',alignment=1)
        self.program['ground_night_detail'].value=5
        self.program['night_detail_enabled'].value=False
        self.target=self.ctx.texture((self.w,self.h),4,dtype='f4');self.fbo=self.ctx.framebuffer([self.target])
        self.program['resolution'].value=(self.w,self.h);self.cloud=None;self.top=None

    def set_night_detail(self,rgb=None,extent_wsen=None):
        """Opt-in native EPSG:4326 static RGB; never infer 2022 light observations.

        North-first pixel-area grid, no antimeridian crossing. Replace, rather
        than add to, the global emissive sample; one-degree interior edge join.
        """
        import moderngl
        if rgb is None:
            with self.ctx:self.program['night_detail_enabled'].value=False
            return
        a=np.asarray(rgb)
        if a.ndim!=3 or a.shape[2]!=3 or a.dtype!=np.uint8 or min(a.shape[:2])<2:
            raise ValueError('Native uint8 RGB regional grid required')
        bounds=np.asarray(extent_wsen,dtype=float)
        if bounds.shape!=(4,) or not np.isfinite(bounds).all():raise ValueError('Finite WSEN extent required')
        west,south,east,north=bounds
        if not (-180<=west<east<=180 and -90<=south<north<=90) or east-west<=2 or north-south<=2:
            raise ValueError('Nonwrapping extent wider than the edge join required')
        if max(a.shape[:2])>self.ctx.info['GL_MAX_TEXTURE_SIZE']:raise ValueError('Regional grid exceeds GPU limit')
        with self.ctx:
            new=self.ctx.texture((a.shape[1],a.shape[0]),3,np.ascontiguousarray(a).tobytes(),alignment=1)
            new.repeat_x=False;new.repeat_y=False;new.build_mipmaps();new.anisotropy=16
            new.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
            self.night_detail.release();self.night_detail=new
            self.program['night_detail_uv'].value=((west+180)/360,(90-north)/180,(east-west)/360,(north-south)/180)
            self.program['night_detail_feather'].value=(1/(east-west),1/(north-south))
            self.program['night_detail_enabled'].value=True

    def update(self,rgba,height,metadata):
        import moderngl
        projection=metadata['projection']
        if projection.get('proj')!='geos' or projection.get('sweep','y')!='y':raise ValueError('Verified AHI sweep-y projection required')
        if rgba.ndim!=3 or rgba.shape[2]!=4 or height.ndim!=2:raise ValueError('Independent native cloud RGBA/height grids required')
        with self.ctx:
            for old in [self.cloud,self.top]:
                if old is not None:old.release()
            a=np.ascontiguousarray(rgba,np.uint8).copy()
            for row in range(0,a.shape[0],256):
                sl=slice(row,row+256)
                a[sl,...,3]=np.rint((a[sl,...,3].astype(np.float32)/255)**self.opacity_gamma*255).astype(np.uint8)
                a[sl,...,:3]=np.rint(a[sl,...,:3].astype(np.float32)*a[sl,...,3:4]/255).astype(np.uint8)
            self.cloud=self.ctx.texture((a.shape[1],a.shape[0]),4,a.tobytes(),alignment=1)
            self.cloud.repeat_x=False;self.cloud.repeat_y=False;self.cloud.build_mipmaps();self.cloud.anisotropy=16
            self.cloud.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
            support=np.isfinite(height)&(height>0)&(height<=20)
            model=np.where(support,height,0).astype(np.float32);model_support=support.copy()
            if self.geometry_bridge_pixels:
                from scipy.ndimage import gaussian_filter
                weight=gaussian_filter(support.astype(np.float32),self.geometry_bridge_pixels,mode='nearest')
                nearby=np.divide(gaussian_filter(model,self.geometry_bridge_pixels,mode='nearest'),weight,
                                 out=np.zeros_like(model),where=weight>.001)
                # Derived display geometry ONLY, not an extension of measured
                # support. Raw height NaNs and source quality masks stay intact.
                model_support=np.clip(weight,0,1)
                model=np.where(weight>.001,nearby,0)
            self.geometry_interpolated_cells=int(((model_support>.001)&~support).sum())
            data=np.ascontiguousarray(np.dstack([model*model_support,model_support.astype(np.float32),support.astype(np.float32)]),np.float32)
            self.top=self.ctx.texture((height.shape[1],height.shape[0]),3,data.tobytes(),alignment=1,dtype='f4')
            self.top.repeat_x=False;self.top.repeat_y=False;self.top.filter=(moderngl.LINEAR,moderngl.LINEAR)
            self.program['source_projection'].value=(projection['a']/1000,projection['b']/1000,projection['h']/1000,math.radians(projection['lon_0']))
            self.program['source_extent'].value=tuple(float(v)/1000 for v in metadata['extent_m'])

    @property
    def device(self):return self.ctx.info['GL_RENDERER']

    def render(self,camera,sun,volume=True,atmosphere=True,airglow=True,debug_projection=False,height_scale=.4,thickness=.8,float_output=False,volume_samples=96,*,deep_ocean_material=False,ocean_reflections=True,city_lights=True,clouds=True,exposure=1.,city_light_gain=2.):
        if self.cloud is None:raise ValueError('Observed frame must be uploaded first')
        if not 0<=height_scale<=.5 or not .2<=thickness<=1.5:raise ValueError('Bounded display height/thickness required')
        if not isinstance(volume_samples,int) or not 32<=volume_samples<=192:raise ValueError('Volume sample count must be32..192')
        if not np.isfinite(exposure) or not .25<=exposure<=2:raise ValueError('Bounded fixed exposure in 0.25..2 required')
        if not np.isfinite(city_light_gain) or not .25<=city_light_gain<=2:raise ValueError('Bounded city-light gain in 0.25..2 required')
        right,up,forward=camera_basis(np.asarray(camera['position']),camera['target'],camera['up'])
        with self.ctx:
            for name,value in [('camera_position',camera['position']),('camera_right',right),('camera_up',up),('camera_forward',forward),('sun_direction',sun)]:
                self.program[name].value=tuple(map(float,value))
            for name,value in [('tan_half_fov',math.tan(math.radians(camera['fov'])/2)),('height_scale',height_scale),('layer_thickness',thickness),
                               ('volume_enabled',volume),('atmosphere_enabled',atmosphere),('airglow_enabled',airglow),('debug_projection',debug_projection)]:
                self.program[name].value=value
            self.program['volume_samples'].value=volume_samples
            for name,value in [('deep_ocean_material',deep_ocean_material),('ocean_reflections_enabled',ocean_reflections),
                               ('city_lights_enabled',city_lights),('clouds_enabled',clouds),('exposure',float(exposure)),('city_light_gain',float(city_light_gain))]:
                self.program[name].value=value
            for i,tex in enumerate(self.textures+[self.cloud,self.top,self.water,self.night_detail]):tex.use(i)
            self.fbo.use();self.ctx.viewport=(0,0,self.w,self.h);self.vao.render(vertices=3)
            pixels=np.frombuffer(self.fbo.read(components=4,dtype='f4'),np.float32).reshape(self.h,self.w,4)[::-1].copy()
        if not np.isfinite(pixels).all():raise ValueError('Nonfinite native volume render')
        if float_output:return pixels
        result=np.rint(np.clip(pixels[...,:3],0,1)*255).astype(np.uint8)
        if (self.w,self.h)!=(self.width,self.height):
            from PIL import Image
            result=np.asarray(Image.fromarray(result).resize((self.width,self.height),Image.Resampling.LANCZOS)).copy()
        return result

    def close(self):
        with self.ctx:
            for tex in self.textures+[self.cloud,self.top,self.water,self.night_detail]:
                if tex is not None:tex.release()
            self.vao.release();self.buffer.release();self.fbo.release();self.target.release();self.program.release()
        self.ctx.release()
