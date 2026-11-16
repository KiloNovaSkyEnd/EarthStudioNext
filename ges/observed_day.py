"""Observed daytime Earth view, not a retrieved cloud-free surface/3D water BSDF.

Land, sea and clouds in the observed region come from the same measured RGB.
No static daytime Earth texture is accepted. Source RGB already contains cloud
and viewing-path effects, so it replaces the rendered daytime pixel once, after
the independent volume/path pass. Existing native rendering remains untouched.
"""
import numpy as np

from .catalog import utc_time
from .goni_film import NativeCloudRenderer
from .solar import sun_direction


def observed_texture(display_rgb, support):
    """Premultiply display-decoded RGB, retaining an independent missing mask."""
    rgb = np.asarray(display_rgb)
    valid = np.asarray(support)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or valid.shape != rgb.shape[:2] or valid.dtype != bool:
        raise ValueError('HxWx3 display RGB and matching boolean observation support required')
    if not np.issubdtype(rgb.dtype, np.floating):
        raise ValueError('Explicit floating display RGB in unit scale required')
    valid = valid & np.isfinite(rgb).all(-1)
    # Enhanced RGB may be outside display gamut; retain original source separately.
    clipped = np.clip(np.where(valid[..., None], rgb, 0), 0, 1)
    linear = np.where(clipped <= .04045, clipped/12.92, ((clipped+.055)/1.055)**2.4)
    return np.dstack([linear, valid.astype(np.float32)]).astype(np.float32)


class ObservedDayRenderer(NativeCloudRenderer):
    """A separate observational mode: source-geometry RGB, 3D/night legacy intact.

    Daytime source clouds are part of the RGB image. They are NOT duplicated
    by the volume pass. This is an observed appearance reference with spherical
    reprojection, not free-view volumetric cloud reconstruction or water optics.
    """
    def _fragment_shader(self):
        shader = super()._fragment_shader()
        shader = shader.replace('uniform sampler2D ocean_mask;', '''uniform sampler2D ocean_mask;
uniform sampler2D observed_day_rgb;
uniform bool observed_ready, observed_coverage_debug, observed_weight_debug;
''')
        anchor = '    if(exposure!=1.)base*=exposure;'
        assert shader.count(anchor) == 1
        shader = shader.replace(anchor, '''    if(observed_weight_debug)base=vec3(0.);
    if(hit){
        vec3 p=camera_position+ray*ground.x;
        vec3 n=normalize(p);
        float weight=c2(0.,.104528,dot(n,sun_direction));
        vec2 uv=source_uv(p);
        float f=dot(n,ray);f=f<0.?-max(abs(f),.03):max(abs(f),.03);
        vec2 ux=source_uv(p+ground.x*(dx-ray*dot(n,dx)/f))-uv;
        vec2 uy=source_uv(p+ground.x*(dy-ray*dot(n,dy)/f))-uv;
        vec4 observation=vec4(0.);
        if(observed_ready&&inside(uv))observation=textureGrad(observed_day_rgb,uv,ux,uy);
        bool supported=observation.a>.999;
        // Deliberate diagnostic hatch: missing daylight is never a static sea.
        float stripe=mod(floor((gl_FragCoord.x+gl_FragCoord.y)/12.),2.);
        vec3 missing=mix(vec3(.024,.009,.024),vec3(.06,.04,.06),stripe);
        vec3 appearance=supported?observation.rgb/max(observation.a,.0001):missing;
        if(observed_coverage_debug)appearance=supported?vec3(0.,1.,0.):missing;
        // The source is apparent display RGB, not albedo. No second cloud or
        // atmosphere integration, no artificial solar relighting of these pixels.
        if(weight>=1.)base=appearance;
        else if(weight>0.)base=mix(base,appearance,weight);
        if(observed_weight_debug)base=vec3(weight);
    }
''' + anchor)
        return shader

    def __init__(self, night, width=1280, height=720, supersample=1., **kwargs):
        # This interface cannot accept or read a static daytime map.
        super().__init__(np.zeros((2, 4, 3), np.uint8), night, width, height, supersample, **kwargs)
        self.observed = None
        self.observation_utc = None
        with self.ctx:
            self.program['observed_day_rgb'].value = 6
            self.program['observed_ready'].value = False
            self.program['observed_coverage_debug'].value = False
            self.program['observed_weight_debug'].value = False

    def set_observation(self, display_rgb, support, metadata):
        """Same native extent as uploaded clouds; timestamps are explicit UTC."""
        import moderngl
        stamp = utc_time(metadata['nominal_utc'])
        if metadata.get('source_fade_applied') is True:
            raise ValueError('Source RGB must not contain a second twilight fade; rebuild from raw bands')
        if stamp.utcoffset().total_seconds() != 0:
            raise ValueError('UTC observation required')
        expected = tuple(metadata['output_shape_yx'])
        if np.shape(display_rgb)[:2] != expected:
            raise ValueError('Observation shape does not match declared native source grid')
        if not hasattr(self, '_cloud_metadata'):
            raise ValueError('Upload cloud geometry/navigation first')
        if stamp != utc_time(self._cloud_metadata['nominal_utc']):
            raise ValueError('Observation and cloud UTC must match')
        if metadata['projection']['proj'] != 'geos' or metadata['projection'].get('sweep', 'y') != 'y':
            raise ValueError('AHI geostationary sweep-y observation required')
        if not np.allclose(metadata['area_extent_m'], self._cloud_metadata['extent_m'], rtol=0, atol=.001):
            raise ValueError('Observation and cloud extents must agree')
        for key in ['a', 'h', 'lon_0']:
            if not np.isclose(metadata['projection'][key], self._cloud_metadata['projection'][key]):
                raise ValueError('Observation and cloud projections must agree')
        a = observed_texture(display_rgb, support)
        with self.ctx:
            new = self.ctx.texture((a.shape[1], a.shape[0]), 4, a.tobytes(), dtype='f4')
            new.repeat_x = False
            new.repeat_y = False
            new.build_mipmaps()
            new.anisotropy = 16
            new.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            if self.observed is not None:
                self.observed.release()
            self.observed = new
            self.program['observed_ready'].value = True
        self.observation_utc = stamp.isoformat()

    def update(self, rgba, height, metadata):
        utc_time(metadata['nominal_utc'])
        super().update(rgba, height, metadata)
        self._cloud_metadata = metadata
        # A previous RGB frame is never silently reused with new geometry/weather.
        with self.ctx:
            self.program['observed_ready'].value = False
        self.observation_utc = None

    def render(self, camera, sun, *args, coverage_debug=False, weight_debug=False, **kwargs):
        if self.observation_utc is None:
            raise ValueError('Upload a matching observation after each cloud update')
        if not np.allclose(sun, sun_direction(utc_time(self.observation_utc)), rtol=0, atol=1e-6):
            raise ValueError('Sun must match the actual observation UTC')
        with self.ctx:
            self.observed.use(6)
            self.program['observed_coverage_debug'].value = coverage_debug
            self.program['observed_weight_debug'].value = weight_debug
        return super().render(camera, sun, *args, **kwargs)

    def close(self):
        if getattr(self, 'observed', None) is not None:
            with self.ctx:
                self.observed.release()
        super().close()
