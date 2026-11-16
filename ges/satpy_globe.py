"""Stock Satpy display pixels on a sphere; only the optional rim is custom.

No custom spectral mapping, cloud opacity, city lights or solar source blend.
The sRGB texture is hardware-decoded before linear filtering and mipmapping.
"""
from pathlib import Path
import numpy as np
from .atmosphere_scattering import VERTEX, camera_basis
from .catalog import utc_time
from .solar import sun_direction
from .observed_atmosphere import resolve_linear_samples

PROFILE = 'satpy-stock-geocolor-soft-rim-v1'


def rim_profile(height_km):
    h = np.asarray(height_km,dtype=float)
    return np.exp(-.5*(h/np.where(h<0,2.,18.))**2)


class SatpyGlobeRenderer:
    def __init__(self, rgb, metadata, width=1280, height=800, supersample=2):
        import moderngl
        if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:
            raise ValueError('Unmodified Satpy uint8 RGB required')
        if list(rgb.shape[:2])!=metadata['shape'] or metadata['composite']!='geo_color':
            raise ValueError('Matching stock GeoColor metadata required')
        projection = metadata['projection']
        if projection.get('proj')!='geos' or projection.get('sweep','y')!='y':
            raise ValueError('AHI sweep-y navigation required')
        self.sun = sun_direction(utc_time(metadata['nominal_utc']))
        self.width,self.height = width,height
        self.w,self.h = width*supersample,height*supersample
        self.ctx = moderngl.create_standalone_context(require=330)
        if max(rgb.shape[:2])>self.ctx.info['GL_MAX_TEXTURE_SIZE']:
            raise ValueError('Native source exceeds GPU texture size')
        self.program = self.ctx.program(vertex_shader=VERTEX,fragment_shader=(Path(__file__).parent/'shaders/satpy_globe.frag').read_text())
        self.buffer=self.ctx.buffer(np.array([[-1,-1],[3,-1],[-1,3]],np.float32).tobytes())
        self.vao=self.ctx.vertex_array(self.program,[(self.buffer,'2f','position')])
        self.texture=self.ctx.texture((rgb.shape[1],rgb.shape[0]),3,np.ascontiguousarray(rgb).tobytes(),alignment=1,internal_format=0x8C41)
        self.texture.repeat_x=False;self.texture.repeat_y=False
        self.texture.build_mipmaps();self.texture.anisotropy=16
        self.texture.filter=(moderngl.LINEAR_MIPMAP_LINEAR,moderngl.LINEAR)
        self.program['geocolor'].value=0
        self.program['source_extent'].value=tuple(np.asarray(metadata['extent'])/1000)
        a=projection['a'];b=projection.get('b',a*(1-1/projection.get('rf',298.257223563)))
        self.program['source_projection'].value=(a/1000,b/1000,projection['h']/1000,np.deg2rad(projection['lon_0']))
        self.program['sun_direction'].value=tuple(self.sun)
        self.program['resolution'].value=(self.w,self.h)
        self.target=self.ctx.texture((self.w,self.h),4,dtype='f4')
        self.fbo=self.ctx.framebuffer([self.target])
        self.device=self.ctx.info['GL_RENDERER']

    def render(self, camera, atmosphere=True, airglow=True):
        import moderngl
        right,up,forward=camera_basis(camera['position'],camera['target'],camera['up'])
        with self.ctx:
            for name,value in [('camera_position',camera['position']),('camera_right',right),('camera_up',up),('camera_forward',forward)]:
                self.program[name].value=tuple(value)
            self.program['tan_half_fov'].value=np.tan(np.deg2rad(camera['fov']/2))
            self.program['atmosphere_enabled'].value=atmosphere
            self.program['airglow_enabled'].value=airglow
            self.texture.use(0);self.fbo.use();self.ctx.viewport=(0,0,self.w,self.h)
            self.vao.render(moderngl.TRIANGLES)
            pixels=np.frombuffer(self.fbo.read(components=3,dtype='f4'),np.float32).reshape(self.h,self.w,3)[::-1].copy()
        return resolve_linear_samples(pixels,self.width,self.height)

    def close(self):
        with self.ctx:
            for obj in [self.vao,self.buffer,self.texture,self.fbo,self.target,self.program]:obj.release()
        self.ctx.release()
