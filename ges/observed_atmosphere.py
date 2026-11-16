"""Opt-in camera-path atmosphere for apparent satellite RGB.

The source already contains an enhanced atmospheric appearance. Extra slant
columns approach full continuous density at tangency. Twilight airlight is
independent of ground VIS availability; IR false colour is not VIS-attenuated.
Zenith-sky fill is approximate, not inversion or full multiple scattering.
"""
import numpy as np
from .observed_day import ObservedDayRenderer


def resolve_linear_samples(encoded_rgb,width,height):
    """Resolve encoded high-resolution samples in linear light, without ringing."""
    values=np.clip(np.asarray(encoded_rgb,dtype=np.float32)[...,:3],0,1)
    linear=np.where(values<=.04045,values/12.92,((values+.055)/1.055)**2.4)
    h,w=linear.shape[:2]
    if h%height==0 and w%width==0:
        linear=linear.reshape(height,h//height,width,w//width,3).mean(axis=(1,3))
    else:
        from PIL import Image
        linear=np.stack([np.asarray(Image.fromarray(linear[...,c]).resize(
            (width,height),Image.Resampling.BOX)) for c in range(3)],axis=-1)
    encoded=np.where(linear<=.0031308,linear*12.92,1.055*linear**(1/2.4)-.055)
    return np.rint(np.clip(encoded,0,1)*255).astype('uint8')


class ObservedAtmosphereRenderer(ObservedDayRenderer):
    def _fragment_shader(self):
        shader = super()._fragment_shader()
        shader = shader.replace('uniform bool observed_ready, observed_coverage_debug, observed_weight_debug;', '''
uniform bool observed_ready, observed_coverage_debug, observed_weight_debug;
uniform sampler2D observed_ir_support;
uniform bool observed_ir_ready;''')
        start = shader.index('    if(observed_weight_debug)base=vec3(0.);')
        end = shader.index('    if(exposure!=1.)base*=exposure;', start)
        composite = shader[start:end]
        shader = shader[:start]+shader[end:]
        # Coverage is a level-zero containing-pixel decision. Mipmap coverage
        # must not turn valid pixels into holes just because a neighbour is NaN.
        composite = composite.replace('bool supported=observation.a>.999;', '''
        ivec2 size=textureSize(observed_day_rgb,0);
        ivec2 cell=clamp(ivec2(floor(uv*vec2(size))),ivec2(0),size-1);
        bool supported=observed_ready&&inside(uv)&&texelFetch(observed_day_rgb,cell,0).a>.999;
        bool filtered=observation.a>.0001;
        supported=supported&&filtered;''')
        composite = composite.replace('vec3 appearance=supported?observation.rgb/max(observation.a,.0001):missing;', '''
        ivec2 ir_size=textureSize(observed_ir_support,0);
        ivec2 ir_cell=clamp(ivec2(floor(uv*vec2(ir_size))),ivec2(0),ir_size-1);
        bool ir_available=observed_ir_ready&&inside(uv)&&texelFetch(observed_ir_support,ir_cell,0).r>.999;
        vec3 appearance=supported?observation.rgb/max(observation.a,.0001):(ir_available?apparent_ir_base:missing);
        apparent_vis_weight=(!supported&&ir_available)?0.:weight;
        apparent_vis_base=appearance;''')
        composite = '''
    vec3 apparent_ir_base=base,apparent_vis_base=vec3(0.);
    float apparent_vis_weight=0.;
''' + composite + '    vec3 apparent_coverage_output=base;\n'
        # Appearance first, camera path second. Never overlay daytime volume
        # clouds a second time on the RGB containing those same source clouds.
        anchor = '    float start=max(atmo.x,0.);finish=min(finish,atmo.y);'
        assert shader.count(anchor) == 1
        shader = shader.replace(anchor, composite+'''
    float observed_path_fraction=1.;
    float ir_haze_weight=0.;
    if(hit){
        vec3 ground_point=camera_position+ray*ground.x;
        vec3 normal=normalize(ground_point);
        float view_mu=clamp(dot(normal,-ray),0.,1.);
        float orbit_radius=source_projection.x+source_projection.z;
        vec3 source_position=orbit_radius*vec3(cos(source_projection.w),sin(source_projection.w),0.);
        float reference_mu=max(dot(normal,normalize(source_position-ground_point)),.02);
        float extra=clamp(1.-view_mu/reference_mu,0.,1.);
        // Restore the complete continuous density column at the tangent.
        // A height cutoff inside, but full density outside, made a hard seam.
        float tangent_column=1.-c2(0.,.35,view_mu);
        observed_path_fraction=max(extra,tangent_column);
        // A twilight IR display is not visible radiance, but leaving its
        // bright false-colour clouds wholly unattenuated makes a hard crust.
        // Fade them achromatically through the same grazing column only.
        ir_haze_weight=(1.-c2(.05,.35,view_mu))*c2(-.104528,0.,dot(normal,sun_direction));
        finish=mix(finish,ground.x,apparent_vis_weight);
    }
''' + anchor)
        anchor = '            vec3 ext=atmosphere_enabled?sigma(rho):vec3(0),source=vec3(0);'
        assert shader.count(anchor) == 1
        shader = shader.replace(anchor, '''
            float path_fraction=observed_path_fraction;
            vec3 ext=atmosphere_enabled?sigma(rho)*path_fraction:vec3(0),source=vec3(0);''')
        shader = shader.replace('void main(){', '''
// Four vertical quadrature cells estimate the Rayleigh zenith sky. The
// hemisphere is represented by this direction for a bounded second-scatter
// fill. This is a display approximation, not full multiple scattering.
vec3 zenith_airlight(vec3 origin){
    vec3 up=normalize(origin),tau=vec3(0.),radiance=vec3(0.);
    float limit=max(TOP-length(origin),0.);
    float bounds[5]=float[5](0.,4.,12.,28.,60.);
    float mu=dot(up,sun_direction),phase=3.*(1.+mu*mu)/(16.*PI);
    for(int j=0;j<4;j++){
        float a=min(bounds[j],limit),b=min(bounds[j+1],limit),ds=b-a;
        if(ds<=0.)break;
        vec3 point=origin+up*(a+b)*.5,rho=density(point);
        vec3 dt=sigma(rho)*ds;
        radiance+=exp(-tau-.5*dt)*BR*rho.x*phase*sunlight(point)*ds;
        tau+=dt;
    }
    return radiance;
}
void main(){''')
        shader = shader.replace('        vec3 tau=vec3(0),light=vec3(0);float mu=dot(ray,sun_direction);', '''
        vec3 sky_fill=atmosphere_enabled?zenith_airlight(camera_position+ray*closest):vec3(0.);
        vec3 tau=vec3(0),light=vec3(0);float mu=dot(ray,sun_direction);''')
        shader = shader.replace('if(atmosphere_enabled)source=(BR*rho.x*pr+BM*rho.y*pm)*sunlight(p)*1.2;', '''
            if(atmosphere_enabled){
                source=(BR*rho.x*pr+BM*rho.y*pm)*sunlight(p)*1.2*path_fraction;
                source+=(BR*rho.x+BM*rho.y)*sky_fill*.5*path_fraction;
            }''')
        shader = shader.replace('        base=base*exp(-tau)+light;', '''
        // IR false colour is not visible radiance: preserve its palette.
        // Visible airlight is still integrated along the SAME camera column,
        // including twilight where ground VIS has already become unavailable.
        float neutral_transmission=exp(-dot(tau,vec3(.2126,.7152,.0722)));
        if(hit)base=apparent_ir_base*(1.-apparent_vis_weight)*mix(1.,neutral_transmission,ir_haze_weight)
                    +apparent_vis_base*apparent_vis_weight*exp(-tau)+light;
        else base=base*neutral_transmission+light;''')
        old = '''if(airglow_enabled){float h=length(p)-R,night=1.-c2(-.12,.04,dot(normalize(p),sun_direction));
                source+=vec3(.8,.38,.10)*exp(-.5*pow((h-90.)/7.,2.))*night*.000015;}'''
        assert shader.count(old) == 1
        shader = shader.replace(old, '''if(airglow_enabled&&!hit){
                float h=length(p)-R;
                float night=1.-c2(-.309017,-.104528,dot(normalize(p),sun_direction));
                // Weak night emission outside the opaque silhouette only.
                // Do not grade an amber layer over the observed ground/clouds.
                source+=vec3(.8,.38,.10)*exp(-.5*pow((h-90.)/7.,2.))*night*.000003;
            }''')
        # Diagnostic output must remain independent of atmosphere settings.
        shader = shader.replace('    if(exposure!=1.)base*=exposure;', '''
    if(observed_coverage_debug)base=apparent_coverage_output;
    if(observed_weight_debug){
        base=vec3(0.);
        if(hit){
            vec3 normal=normalize(camera_position+ray*ground.x);
            base=vec3(c2(0.,.104528,dot(normal,sun_direction)));
        }
    }
    if(exposure!=1.)base*=exposure;''')
        # Pixel-cone integration at the analytic limb; do not blur the image.
        # Keep diagnostics as containing-pixel/central-ray evidence.
        header='''void main(){
    vec2 screen=(2.*gl_FragCoord.xy-resolution)/resolution.y;
    vec3 ray=normalize(camera_forward+tan_half_fov*(camera_right*screen.x+camera_up*screen.y));
    vec3 dx=dFdx(ray),dy=dFdy(ray);'''
        assert shader.count(header)==1
        shader=shader.replace(header,'vec4 observed_ray_sample(vec3 ray,vec3 dx,vec3 dy){')
        projection_return='frag_color=vec4(uv,0,1);return;'
        assert shader.count(projection_return)==1
        shader=shader.replace(projection_return,'return vec4(uv,0.,1.);')
        output='frag_color=vec4(clamp(srgb(base),0.,1.),1.);'
        assert shader.count(output)==1
        shader=shader.replace(output,'return vec4(clamp(srgb(base),0.,1.),1.);')
        shader+='''
uniform bool observed_limb_antialias;
void main(){
    vec2 screen=(2.*gl_FragCoord.xy-resolution)/resolution.y;
    vec3 ray=normalize(camera_forward+tan_half_fov*(camera_right*screen.x+camera_up*screen.y));
    vec3 dx=dFdx(ray),dy=dFdy(ray);
    float tangent_height=length(cross(camera_position,ray))-R;
    float footprint=max(fwidth(tangent_height),.001);
    // Include the existing <=8.4km cloud shell as well as ground tangency.
    bool near_limb=abs(tangent_height)<12.+1.5*footprint;
    if(!observed_limb_antialias||!near_limb||debug_projection||observed_coverage_debug||observed_weight_debug){
        frag_color=observed_ray_sample(ray,dx,dy);return;
    }
    vec3 sum_linear=vec3(0.);
    for(int y=0;y<4;y++)for(int x=0;x<4;x++){
        vec2 offset=(vec2(x,y)+.5)/4.-.5;
        vec3 subray=normalize(ray+offset.x*dx+offset.y*dy);
        sum_linear+=linear_rgb(observed_ray_sample(subray,dx,dy).rgb);
    }
    frag_color=vec4(clamp(srgb(sum_linear/16.),0.,1.),1.);
}
'''
        return shader

    def __init__(self,*args,limb_antialias=True,linear_resolve=True,**kwargs):
        if not isinstance(limb_antialias,bool) or not isinstance(linear_resolve,bool):
            raise ValueError('Boolean limb antialias/resolve settings required')
        self.linear_resolve=linear_resolve
        super().__init__(*args,**kwargs)
        with self.ctx:
            self.program['observed_limb_antialias'].value=limb_antialias
            self.ir_support=self.ctx.texture((1,1),1,b'\x00',alignment=1)
            self.program['observed_ir_support'].value=7
            self.program['observed_ir_ready'].value=False

    def set_ir_support(self,support,metadata):
        """Separate actual same-scan IR coverage, never inferred from opacity."""
        from .catalog import utc_time
        values=np.asarray(support)
        if values.dtype!=bool or values.shape!=tuple(metadata['output_shape_yx']):
            raise ValueError('Boolean same-grid actual IR coverage required')
        if utc_time(metadata['nominal_utc'])!=utc_time(self._cloud_metadata['nominal_utc']):
            raise ValueError('IR coverage and cloud UTC must match')
        first,second=metadata['projection'],self._cloud_metadata['projection']
        def axes(p):
            return [p['a'],p.get('b',p['a']*(1.-1./p.get('rf',298.257223563))),p['h'],p['lon_0']]
        if first.get('proj')!='geos' or first.get('sweep','y')!=second.get('sweep','y') or not np.allclose(
            axes(first),axes(second),rtol=0,atol=.001) or not np.allclose(
            metadata['area_extent_m'],self._cloud_metadata['extent_m'],rtol=0,atol=.001):
            raise ValueError('IR coverage navigation must match cloud grid')
        with self.ctx:
            new=self.ctx.texture((values.shape[1],values.shape[0]),1,
                                 (values.astype('uint8')*255).tobytes(),alignment=1)
            new.repeat_x=False;new.repeat_y=False
            self.ir_support.release();self.ir_support=new
            self.program['observed_ir_ready'].value=True

    def update(self,*args,**kwargs):
        super().update(*args,**kwargs)
        with self.ctx:
            self.program['observed_ir_ready'].value=False

    def render(self,*args,**kwargs):
        with self.ctx:
            self.ir_support.use(7)
        # Preserve the existing raw supersampled float-output contract.
        float_requested=args[8] if len(args)>8 else kwargs.get('float_output',False)
        if float_requested or not self.linear_resolve or (self.w,self.h)==(self.width,self.height):
            return super().render(*args,**kwargs)
        positional=list(args)
        options=dict(kwargs)
        if len(positional)>8:
            positional[8]=True
        else:
            options['float_output']=True
        samples=super().render(*positional,**options)
        return resolve_linear_samples(samples,self.width,self.height)

    def close(self):
        with self.ctx:
            self.ir_support.release()
        super().close()
